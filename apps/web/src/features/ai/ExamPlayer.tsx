import { useMutation } from "@tanstack/react-query";
import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Flag,
  LayoutGrid,
  RotateCcw,
  Target,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Markdown } from "../../components/Markdown";
import { api, type QuestionOut, type QuizOut } from "../../lib/api";
import { answerText, type Grade, gradeResponse, responseText } from "./quizGrading";
import "./exam.css";

const TYPE_LABELS: Record<string, string> = {
  mcq: "Multiple choice",
  tf: "True or false",
  short: "Short answer",
  identification: "Identification",
  enumeration: "Enumeration",
  output: "Predict the output",
  essay: "Essay",
  coding: "Coding",
};

type Saved = {
  answers: Record<number, string>;
  flagged: number[];
  index: number;
  startedAt: number;
  submittedAt?: number;
  selfGrades?: Record<number, "right" | "wrong">;
};

const storeKey = (id: number) => `manabi-exam-${id}`;

function loadSaved(id: number): Saved | null {
  try {
    const raw = localStorage.getItem(storeKey(id));
    return raw ? (JSON.parse(raw) as Saved) : null;
  } catch {
    return null;
  }
}

function save(id: number, s: Saved) {
  try {
    localStorage.setItem(storeKey(id), JSON.stringify(s));
  } catch {
    /* storage unavailable: the exam still works, it just won't survive a reload */
  }
}

function clearSaved(id: number) {
  try {
    localStorage.removeItem(storeKey(id));
  } catch {
    /* ignore */
  }
}

function fmtTime(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** The answer area for one question, in exam mode: nothing is revealed. */
function AnswerInput({
  q,
  value,
  onChange,
}: {
  q: QuestionOut;
  value: string;
  onChange: (v: string) => void;
}) {
  if (q.qtype === "mcq" && q.options) {
    return (
      <div className="exam-options" role="radiogroup">
        {q.options.map((opt, i) => (
          <button
            key={i}
            type="button"
            role="radio"
            aria-checked={value === String(i)}
            className={`exam-option${value === String(i) ? " selected" : ""}`}
            onClick={() => onChange(value === String(i) ? "" : String(i))}
          >
            <span className="exam-option-key">{String.fromCharCode(65 + i)}</span>
            <span className="exam-option-text">
              <Markdown className="exam-option-md">{opt}</Markdown>
            </span>
          </button>
        ))}
      </div>
    );
  }
  if (q.qtype === "tf") {
    return (
      <div className="exam-options tf" role="radiogroup">
        {["true", "false"].map((v) => (
          <button
            key={v}
            type="button"
            role="radio"
            aria-checked={value === v}
            className={`exam-option${value === v ? " selected" : ""}`}
            onClick={() => onChange(value === v ? "" : v)}
          >
            <span className="exam-option-key">{v === "true" ? "T" : "F"}</span>
            <span className="exam-option-text">{v === "true" ? "True" : "False"}</span>
          </button>
        ))}
      </div>
    );
  }
  const multiline =
    q.qtype === "output" || q.qtype === "coding" || q.qtype === "essay" || q.qtype === "enumeration";
  if (multiline) {
    return (
      <label className="exam-field">
        <span className="field-label">
          {q.qtype === "output"
            ? "Exact output, line breaks included"
            : q.qtype === "enumeration"
              ? "One item per line"
              : q.qtype === "coding"
                ? "Your code"
                : "Your answer"}
        </span>
        <textarea
          className={`input exam-textarea${q.qtype === "output" || q.qtype === "coding" ? " mono" : ""}`}
          rows={q.qtype === "coding" || q.qtype === "essay" ? 7 : 4}
          value={value}
          spellCheck={q.qtype !== "output" && q.qtype !== "coding"}
          onChange={(e) => onChange(e.target.value)}
        />
      </label>
    );
  }
  return (
    <label className="exam-field">
      <span className="field-label">
        {q.qtype === "identification" ? "The term" : "Your answer"}
      </span>
      <input className="input" value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function Navigator({
  questions,
  answers,
  flagged,
  index,
  onPick,
  grades,
}: {
  questions: QuestionOut[];
  answers: Record<number, string>;
  flagged: Set<number>;
  index: number;
  onPick: (i: number) => void;
  grades?: Grade[];
}) {
  return (
    <div className="exam-grid">
      {questions.map((q, i) => {
        const done = (answers[q.id] ?? "").trim() !== "";
        const g = grades?.[i];
        const cls = [
          "exam-cell",
          done ? "done" : "",
          flagged.has(q.id) ? "flagged" : "",
          i === index ? "current" : "",
          g ? `g-${g}` : "",
        ]
          .filter(Boolean)
          .join(" ");
        return (
          <button
            key={q.id}
            type="button"
            className={cls}
            onClick={() => onPick(i)}
            aria-label={`Question ${i + 1}${done ? ", answered" : ""}${flagged.has(q.id) ? ", flagged" : ""}`}
          >
            {i + 1}
          </button>
        );
      })}
    </div>
  );
}

// ── Results ─────────────────────────────────────────────────────────────

function ReviewItem({
  n,
  q,
  response,
  grade,
  moduleTitle,
  onSelfGrade,
}: {
  n: number;
  q: QuestionOut;
  response: string | undefined;
  grade: Grade;
  moduleTitle?: string;
  onSelfGrade: (g: "right" | "wrong") => void;
}) {
  const [open, setOpen] = useState(grade !== "right");
  const mine = responseText(q, response);
  const right = answerText(q);
  const asCode = q.qtype === "output" || q.qtype === "coding";
  return (
    <li className={`exam-review-item g-${grade}`}>
      <button type="button" className="exam-review-head" onClick={() => setOpen((v) => !v)}>
        <span className="exam-review-n mono">{n}</span>
        <span className="exam-review-mark" aria-hidden>
          {grade === "right" ? <Check size={15} /> : grade === "wrong" ? <X size={15} /> : <CircleHelp size={15} />}
        </span>
        <span className="exam-review-title">
          {q.topic || TYPE_LABELS[q.qtype]}
          {moduleTitle && <span className="exam-review-module">{moduleTitle}</span>}
        </span>
        <ChevronDown size={16} className={`exam-review-chev${open ? " open" : ""}`} />
      </button>
      {open && (
        <div className="exam-review-body">
          <Markdown className="quiz-question">{q.prompt}</Markdown>
          {q.qtype === "mcq" && q.options && (
            <ol className="exam-review-options" type="A">
              {q.options.map((o, i) => (
                <li
                  key={i}
                  className={
                    q.answer.kind === "mcq" && i === q.answer.correct_option
                      ? "is-key"
                      : String(i) === response
                        ? "is-mine"
                        : ""
                  }
                >
                  <Markdown className="exam-option-md">{o}</Markdown>
                </li>
              ))}
            </ol>
          )}
          <div className="exam-answers">
            <div>
              <span className="field-label">Your answer</span>
              {mine ? (
                asCode ? <pre className="quiz-output-block">{mine}</pre> : <p>{mine}</p>
              ) : (
                <p className="exam-muted">No answer</p>
              )}
            </div>
            <div>
              <span className="field-label">
                {q.qtype === "output" && q.answer.kind === "output" && q.answer.verified === "executed"
                  ? "Correct output (verified by running the code)"
                  : "Correct answer"}
              </span>
              {asCode ? <pre className="quiz-output-block">{right}</pre> : <Markdown>{right}</Markdown>}
            </div>
          </div>
          {q.explanation && (
            <div className="exam-explanation">
              <span className="field-label">Why</span>
              <Markdown className="quiz-explanation">{q.explanation}</Markdown>
            </div>
          )}
          {grade === "self" && (
            <div className="exam-selfgrade">
              <span>Compare with the answer above, then mark it:</span>
              <button type="button" className="btn grade-wrong" onClick={() => onSelfGrade("wrong")}>
                I got it wrong
              </button>
              <button type="button" className="btn grade-right" onClick={() => onSelfGrade("right")}>
                I got it right
              </button>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function Results({
  quiz,
  answers,
  grades,
  elapsed,
  moduleTitles,
  onSelfGrade,
  onRetake,
  onExit,
  onPracticeWeak,
}: {
  quiz: QuizOut;
  answers: Record<number, string>;
  grades: Grade[];
  elapsed: number;
  moduleTitles: Record<number, string>;
  onSelfGrade: (qid: number, g: "right" | "wrong") => void;
  onRetake: () => void;
  onExit: () => void;
  onPracticeWeak?: (topics: string[], moduleIds: number[]) => void;
}) {
  const [filter, setFilter] = useState<"all" | "wrong" | "self">("all");
  const right = grades.filter((g) => g === "right").length;
  const wrong = grades.filter((g) => g === "wrong").length;
  const pending = grades.filter((g) => g === "self").length;
  const graded = right + wrong;
  const pct = graded ? Math.round((right / graded) * 100) : 0;

  const byModule = useMemo(() => {
    const m = new Map<number | null, { right: number; total: number }>();
    quiz.questions.forEach((q, i) => {
      if (grades[i] === "self") return;
      const k = q.module_id ?? null;
      const cur = m.get(k) ?? { right: 0, total: 0 };
      cur.total += 1;
      if (grades[i] === "right") cur.right += 1;
      m.set(k, cur);
    });
    return [...m.entries()];
  }, [quiz.questions, grades]);

  const weak = useMemo(() => {
    const t = new Map<string, { wrong: number; total: number; modules: Set<number> }>();
    quiz.questions.forEach((q, i) => {
      const key = (q.topic || "").trim();
      if (!key) return;
      const cur = t.get(key) ?? { wrong: 0, total: 0, modules: new Set<number>() };
      cur.total += 1;
      if (grades[i] === "wrong") cur.wrong += 1;
      if (q.module_id) cur.modules.add(q.module_id);
      t.set(key, cur);
    });
    return [...t.entries()]
      .filter(([, v]) => v.wrong > 0)
      .sort((a, b) => b[1].wrong - a[1].wrong || a[0].localeCompare(b[0]))
      .slice(0, 8);
  }, [quiz.questions, grades]);

  const verdict =
    graded === 0
      ? "Mark the open answers below to get a score."
      : pct >= 85
        ? "Exam-ready on this set. Spend the time on whatever you missed."
        : pct >= 70
          ? "Solid. The misses below are where the marks are."
          : "Go back through the topics below before retaking.";

  const visible = quiz.questions
    .map((q, i) => ({ q, i }))
    .filter(({ i }) => filter === "all" || grades[i] === filter);

  return (
    <div className="exam-results">
      <section className="exam-score">
        <div className="exam-score-figure">
          <span className="exam-score-pct">{pct}</span>
          <span className="exam-score-unit">%</span>
        </div>
        <div className="exam-score-meta">
          <p className="exam-score-line">
            <strong>{right}</strong> right, <strong>{wrong}</strong> wrong
            {pending > 0 && (
              <>
                , <strong>{pending}</strong> to mark yourself
              </>
            )}
            <span className="exam-muted"> in {fmtTime(elapsed)}</span>
          </p>
          <p className="exam-score-verdict">{verdict}</p>
          <div className="exam-score-actions">
            {onPracticeWeak && weak.length > 0 && (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() =>
                  onPracticeWeak(
                    weak.map(([t]) => t),
                    [...new Set(weak.flatMap(([, v]) => [...v.modules]))],
                  )
                }
              >
                <Target size={15} strokeWidth={1.75} /> Drill weak topics
              </button>
            )}
            <button type="button" className="btn" onClick={onRetake}>
              <RotateCcw size={15} strokeWidth={1.75} /> Retake
            </button>
            <button type="button" className="btn" onClick={onExit}>
              Done
            </button>
          </div>
        </div>
      </section>

      <section className="exam-breakdown">
        {byModule.length > 1 && (
          <div className="exam-breakdown-block">
            <h3>By module</h3>
            <ul className="exam-bars">
              {byModule.map(([mid, v]) => {
                const p = v.total ? Math.round((v.right / v.total) * 100) : 0;
                return (
                  <li key={String(mid)}>
                    <span className="exam-bar-label">{mid != null ? moduleTitles[mid] ?? "Module" : "Other"}</span>
                    <span className="exam-meter" style={{ width: `${Math.max(p, 2)}%` }} data-low={p < 70 || undefined} />
                    <span className="exam-bar-num mono">
                      {v.right}/{v.total}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
        {weak.length > 0 && (
          <div className="exam-breakdown-block">
            <h3>Topics to revisit</h3>
            <ul className="exam-weak">
              {weak.map(([t, v]) => (
                <li key={t}>
                  <span>{t}</span>
                  <span className="mono exam-muted">
                    {v.wrong} of {v.total} missed
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section className="exam-review">
        <div className="exam-review-bar">
          <h3>Review</h3>
          <div className="seg" role="tablist">
            {(
              [
                ["all", `All ${quiz.questions.length}`],
                ["wrong", `Wrong ${wrong}`],
                ["self", `To mark ${pending}`],
              ] as const
            ).map(([k, label]) => (
              <button
                key={k}
                type="button"
                role="tab"
                aria-selected={filter === k}
                className={`seg-btn${filter === k ? " active" : ""}`}
                onClick={() => setFilter(k)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <ol className="exam-review-list">
          {visible.map(({ q, i }) => (
            <ReviewItem
              key={q.id}
              n={i + 1}
              q={q}
              response={answers[q.id]}
              grade={grades[i]}
              moduleTitle={q.module_id ? moduleTitles[q.module_id] : undefined}
              onSelfGrade={(g) => onSelfGrade(q.id, g)}
            />
          ))}
          {visible.length === 0 && <p className="exam-muted">Nothing here.</p>}
        </ol>
      </section>
    </div>
  );
}

// ── The exam ────────────────────────────────────────────────────────────

/** Exam mode: every question is answered before anything is revealed, then a
 * results screen breaks the score down by module and topic. Progress survives
 * a reload (localStorage, per device). */
export function ExamPlayer({
  quiz,
  moduleTitles = {},
  onExit,
  onPracticeWeak,
}: {
  quiz: QuizOut;
  moduleTitles?: Record<number, string>;
  onExit: () => void;
  onPracticeWeak?: (topics: string[], moduleIds: number[]) => void;
}) {
  const id = quiz.artifact_id;
  const questions = quiz.questions;
  const initial = useRef<Saved>(
    loadSaved(id) ?? { answers: {}, flagged: [], index: 0, startedAt: Date.now() },
  );
  const [answers, setAnswers] = useState<Record<number, string>>(initial.current.answers);
  const [flagged, setFlagged] = useState<Set<number>>(new Set(initial.current.flagged));
  const [index, setIndex] = useState(Math.min(initial.current.index, Math.max(0, questions.length - 1)));
  const [startedAt, setStartedAt] = useState(initial.current.startedAt);
  const [submittedAt, setSubmittedAt] = useState<number | undefined>(initial.current.submittedAt);
  const [selfGrades, setSelfGrades] = useState<Record<number, "right" | "wrong">>(
    initial.current.selfGrades ?? {},
  );
  const [now, setNow] = useState(Date.now());
  const [sheet, setSheet] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const attemptId = useRef<number | null>(null);

  const submitted = submittedAt != null;

  useEffect(() => {
    save(id, { answers, flagged: [...flagged], index, startedAt, submittedAt, selfGrades });
  }, [id, answers, flagged, index, startedAt, submittedAt, selfGrades]);

  useEffect(() => {
    if (submitted) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [submitted]);

  const grades: Grade[] = useMemo(
    () =>
      questions.map((q) => {
        const g = gradeResponse(q, answers[q.id]);
        return g === "self" ? (selfGrades[q.id] ?? "self") : g;
      }),
    [questions, answers, selfGrades],
  );

  const record = useMutation({
    mutationFn: async (finalGrades: Grade[]) => {
      if (attemptId.current == null) {
        const r = await api.post<{ attempt_id: number }>(`/api/quizzes/${id}/attempts`);
        attemptId.current = r.attempt_id;
      }
      const right = finalGrades.filter((g) => g === "right").length;
      const graded = finalGrades.filter((g) => g !== "self").length;
      const responses: Record<string, unknown> = {};
      questions.forEach((q, i) => {
        responses[q.id] = { response: answers[q.id] ?? "", grade: finalGrades[i] };
      });
      return api.patch(`/api/quiz-attempts/${attemptId.current}`, {
        responses,
        score: graded ? Math.round((right / graded) * 1000) / 10 : 0,
        finished: true,
      });
    },
  });

  // Record on submit and again when self-grades change — but only for changes
  // made in this session (reopening saved results must not log a new attempt).
  const dirty = useRef(false);
  useEffect(() => {
    if (submitted && dirty.current) record.mutate(grades);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [submitted, selfGrades]);

  const q = questions[index];
  const answeredCount = questions.filter((x) => (answers[x.id] ?? "").trim() !== "").length;
  const unanswered = questions.length - answeredCount;

  function go(i: number) {
    setIndex(Math.max(0, Math.min(questions.length - 1, i)));
    setSheet(false);
  }

  function toggleFlag() {
    if (!q) return;
    setFlagged((prev) => {
      const n = new Set(prev);
      if (n.has(q.id)) n.delete(q.id);
      else n.add(q.id);
      return n;
    });
  }

  function submit() {
    dirty.current = true;
    setConfirming(false);
    setSubmittedAt(Date.now());
    window.scrollTo({ top: 0 });
  }

  function retake() {
    clearSaved(id);
    attemptId.current = null;
    setAnswers({});
    setFlagged(new Set());
    setIndex(0);
    setStartedAt(Date.now());
    setSubmittedAt(undefined);
    setSelfGrades({});
  }

  // Keyboard: arrows move, A-D / T-F choose, F flags (desktop convenience).
  useEffect(() => {
    if (submitted) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "ArrowRight") go(index + 1);
      else if (e.key === "ArrowLeft") go(index - 1);
      else if (!q) return;
      else if (q.qtype === "mcq" && /^[a-d]$/i.test(e.key)) {
        const i = e.key.toLowerCase().charCodeAt(0) - 97;
        if (q.options && i < q.options.length) setAnswers((a) => ({ ...a, [q.id]: String(i) }));
      } else if (q.qtype === "tf" && /^[tf]$/i.test(e.key)) {
        setAnswers((a) => ({ ...a, [q.id]: e.key.toLowerCase() === "t" ? "true" : "false" }));
      } else if (e.key === "f" || e.key === "F") toggleFlag();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, q, submitted]);

  if (questions.length === 0) {
    return (
      <div className="exam-empty">
        <p>This exam has no questions left to show.</p>
        <button type="button" className="btn" onClick={onExit}>
          Back
        </button>
      </div>
    );
  }

  if (submitted) {
    return (
      <div className="exam">
        <header className="exam-bar">
          <button type="button" className="btn exam-exit" onClick={onExit}>
            <ChevronLeft size={16} strokeWidth={1.75} /> Back
          </button>
          <div className="exam-bar-title">
            <strong>{quiz.title}</strong>
            <span>Results</span>
          </div>
        </header>
        <Results
          quiz={quiz}
          answers={answers}
          grades={grades}
          elapsed={(submittedAt ?? now) - startedAt}
          moduleTitles={moduleTitles}
          onSelfGrade={(qid, g) => {
            dirty.current = true;
            setSelfGrades((s) => ({ ...s, [qid]: g }));
          }}
          onRetake={retake}
          onExit={onExit}
          onPracticeWeak={onPracticeWeak}
        />
      </div>
    );
  }

  const value = (q && answers[q.id]) ?? "";
  const moduleTitle = q?.module_id ? moduleTitles[q.module_id] : undefined;

  return (
    <div className="exam">
      <header className="exam-bar">
        <button type="button" className="btn exam-exit" onClick={onExit} title="Your answers are kept on this device">
          <ChevronLeft size={16} strokeWidth={1.75} /> Exit
        </button>
        <div className="exam-bar-title">
          <strong>{quiz.title}</strong>
          <span>
            {answeredCount} of {questions.length} answered
          </span>
        </div>
        <span className="exam-timer mono" aria-label="Time elapsed">
          {fmtTime(now - startedAt)}
        </span>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => (unanswered > 0 ? setConfirming(true) : submit())}
        >
          Submit
        </button>
      </header>
      <div className="exam-progress" aria-hidden>
        <span style={{ transform: `scaleX(${answeredCount / questions.length})` }} />
      </div>

      <div className="exam-body">
        <main className="exam-q" key={q.id}>
          <div className="exam-q-meta">
            <span className="exam-q-n">Question {index + 1}</span>
            <span className="exam-q-type">{TYPE_LABELS[q.qtype] ?? q.qtype}</span>
            {(q.topic || moduleTitle) && (
              <span className="exam-q-topic">{[q.topic, moduleTitle].filter(Boolean).join(", ")}</span>
            )}
          </div>
          <Markdown className="quiz-question exam-prompt">{q.prompt}</Markdown>
          <AnswerInput q={q} value={value} onChange={(v) => setAnswers((a) => ({ ...a, [q.id]: v }))} />

          <footer className="exam-q-nav">
            <button type="button" className="btn" onClick={() => go(index - 1)} disabled={index === 0}>
              <ChevronLeft size={16} strokeWidth={1.75} /> Previous
            </button>
            <button
              type="button"
              className={`btn exam-flag${flagged.has(q.id) ? " on" : ""}`}
              onClick={toggleFlag}
              aria-pressed={flagged.has(q.id)}
            >
              <Flag size={15} strokeWidth={1.75} /> {flagged.has(q.id) ? "Flagged" : "Flag"}
            </button>
            <button type="button" className="btn exam-sheet-btn" onClick={() => setSheet(true)}>
              <LayoutGrid size={15} strokeWidth={1.75} /> {index + 1}/{questions.length}
            </button>
            {index + 1 < questions.length ? (
              <button type="button" className="btn btn-primary" onClick={() => go(index + 1)}>
                Next <ChevronRight size={16} strokeWidth={2} />
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => (unanswered > 0 ? setConfirming(true) : submit())}
              >
                Finish
              </button>
            )}
          </footer>
        </main>

        <aside className="exam-side" aria-label="Questions">
          <div className="exam-side-head">
            <span>Questions</span>
            <span className="exam-muted">{flagged.size > 0 && `${flagged.size} flagged`}</span>
          </div>
          <Navigator questions={questions} answers={answers} flagged={flagged} index={index} onPick={go} />
          <p className="exam-side-hint">Arrow keys move. A to D picks an option. F flags.</p>
        </aside>
      </div>

      {sheet &&
        createPortal(
          <div className="exam-sheet-overlay" onClick={() => setSheet(false)}>
            <div className="exam-sheet" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Questions">
              <div className="exam-side-head">
                <span>
                  {answeredCount} of {questions.length} answered
                  {flagged.size > 0 && `, ${flagged.size} flagged`}
                </span>
                <button type="button" className="modal-close" onClick={() => setSheet(false)} aria-label="Close">
                  <X size={18} strokeWidth={1.5} />
                </button>
              </div>
              <Navigator questions={questions} answers={answers} flagged={flagged} index={index} onPick={go} />
            </div>
          </div>,
          document.body,
        )}

      {confirming &&
        createPortal(
          <div className="exam-sheet-overlay center" onClick={() => setConfirming(false)}>
            <div className="exam-confirm" onClick={(e) => e.stopPropagation()} role="alertdialog">
              <h3>Submit with {unanswered} unanswered?</h3>
              <p>Unanswered questions count as wrong.</p>
              <div className="exam-confirm-actions">
                <button type="button" className="btn" onClick={() => setConfirming(false)}>
                  Keep going
                </button>
                <button type="button" className="btn btn-primary" onClick={submit}>
                  Submit now
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}
