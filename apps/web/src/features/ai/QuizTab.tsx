import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ChevronRight, ListChecks, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  api,
  type GenerationMode,
  type JobRef,
  type ModuleOut,
  type QuestionOut,
  type QuizListItem,
  type QuizOut,
} from "../../lib/api";
import { Markdown } from "../../components/Markdown";
import {
  AiOfflineBanner,
  CitationPill,
  JobProgress,
  useAiOnline,
  useGenerationJob,
} from "./common";
import { SourcesPicker } from "./SourcesPicker";
import "./quiz.css";

const TYPE_LABELS: Record<string, string> = {
  mcq: "Multiple choice",
  tf: "True / False",
  short: "Short answer",
  identification: "Identification",
  enumeration: "Enumeration",
  output: "Predict output",
  essay: "Essay",
  coding: "Coding",
};

// Grading style per type: self-graded types show the model answer and let the
// student judge; auto-checked types compute a verdict client-side (with an
// override link for wording edge cases); mcq/tf grade exactly.
const SELF_GRADED = new Set(["short", "essay", "coding"]);

// ── Client-side answer matching (deliberately lenient — the override
// buttons are the escape hatch for wording edge cases) ────────────────────

const norm = (s: string) =>
  s
    .toLowerCase()
    .normalize("NFKC")
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();

function fuzzyEqual(a: string, b: string): boolean {
  const na = norm(a);
  const nb = norm(b);
  if (!na || !nb) return false;
  if (na === nb || na.includes(nb) || nb.includes(na)) return true;
  const ta = na.split(" ");
  const tb = new Set(nb.split(" "));
  const overlap = ta.filter((t) => tb.has(t)).length;
  return overlap / Math.max(ta.length, tb.size) >= 0.6;
}

// Exact-output compare: CRLF-safe, trailing spaces and blank lines ignored.
const normOutput = (s: string) =>
  s
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((l) => l.trimEnd())
    .join("\n")
    .replace(/\n+$/, "")
    .trim();

/** Greedy 1:1 match of the student's lines against the answer items. */
function matchEnumeration(userLines: string[], items: string[]): boolean[] {
  const remaining = userLines.filter((l) => l.trim());
  return items.map((item) => {
    const i = remaining.findIndex((l) => fuzzyEqual(l, item));
    if (i === -1) return false;
    remaining.splice(i, 1);
    return true;
  });
}

// ── Taking a quiz ─────────────────────────────────────────────

function QuizPlayer({
  quiz,
  onExit,
  onDebrief,
}: {
  quiz: QuizOut;
  onExit: () => void;
  onDebrief: (missed: string[]) => void;
}) {
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const [shortInput, setShortInput] = useState(""); // short + identification
  const [enumInput, setEnumInput] = useState(""); // enumeration, one per line
  const [longInput, setLongInput] = useState(""); // essay / coding / output
  const [results, setResults] = useState<boolean[]>([]);
  const [attemptId, setAttemptId] = useState<number | null>(null);
  const [responses, setResponses] = useState<Record<string, unknown>>({});

  const started = useRef(false);
  const start = useMutation({
    mutationFn: () =>
      api.post<{ attempt_id: number }>(`/api/quizzes/${quiz.artifact_id}/attempts`),
    onSuccess: (r) => setAttemptId(r.attempt_id),
  });
  useEffect(() => {
    if (!started.current) {
      started.current = true;
      start.mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const question: QuestionOut | undefined = quiz.questions[index];
  const finished = index >= quiz.questions.length;

  function isCorrect(q: QuestionOut, response: string): boolean {
    if (q.answer.kind === "mcq") return Number(response) === q.answer.correct_option;
    if (q.answer.kind === "tf") return (response === "true") === q.answer.value;
    return response === "self-right"; // short answers are self-scored
  }

  function check(response: string) {
    setSelected(response);
    setChecked(true);
  }

  function next(correct: boolean) {
    const q = question!;
    const typed =
      q.qtype === "enumeration"
        ? enumInput
        : q.qtype === "essay" || q.qtype === "coding" || q.qtype === "output"
          ? longInput
          : shortInput;
    const newResults = [...results, correct];
    const newResponses = { ...responses, [q.id]: selected ?? typed };
    setResults(newResults);
    setResponses(newResponses);
    setChecked(false);
    setSelected(null);
    setShortInput("");
    setEnumInput("");
    setLongInput("");
    setIndex((i) => i + 1);
    const done = index + 1 >= quiz.questions.length;
    if (attemptId != null) {
      const score = newResults.filter(Boolean).length / quiz.questions.length;
      api
        .patch(`/api/quiz-attempts/${attemptId}`, {
          responses: newResponses,
          score: done ? Math.round(score * 1000) / 10 : null,
          finished: done,
        })
        .catch(() => undefined);
    }
  }

  if (finished) {
    const right = results.filter(Boolean).length;
    const missed = quiz.questions
      .filter((_, i) => !results[i])
      .map((q) => q.prompt);
    return (
      <div className="quiz-results">
        <h3>
          {right} / {quiz.questions.length}
        </h3>
        <p className="quiz-results-sub">
          {right === quiz.questions.length
            ? "Perfect score."
            : right >= quiz.questions.length * 0.7
              ? "Solid — review the ones you missed."
              : "Worth another pass through the material."}
        </p>
        <div className="quiz-results-actions">
          {missed.length > 0 && (
            <button className="btn" onClick={() => onDebrief(missed)}>
              Steven's debrief
            </button>
          )}
          <button className="btn btn-primary" onClick={onExit}>
            Back to quizzes
          </button>
        </div>
      </div>
    );
  }
  if (!question) return null;

  const correctResponse =
    checked &&
    selected !== null &&
    (question.answer.kind === "mcq" || question.answer.kind === "tf")
      ? isCorrect(question, selected)
      : null;
  // Auto-checked open types: verdict computed from the typed answer.
  const enumHits =
    checked && question.answer.kind === "enumeration"
      ? matchEnumeration(enumInput.split("\n"), question.answer.items)
      : null;
  const verdict: boolean | null = !checked
    ? null
    : question.answer.kind === "identification"
      ? fuzzyEqual(shortInput, question.answer.text)
      : question.answer.kind === "output"
        ? normOutput(longInput) === normOutput(question.answer.text)
        : enumHits !== null
          ? enumHits.every(Boolean)
          : null;

  return (
    <div className="quiz-player">
      <div className="review-meta">
        <span className="mono">
          {index + 1} / {quiz.questions.length}
        </span>
        <button className="btn" onClick={onExit}>
          Exit quiz
        </button>
      </div>

      <Markdown className="quiz-question">{question.prompt}</Markdown>

      {question.qtype === "mcq" && question.options && (
        <div className="quiz-options">
          {question.options.map((opt, i) => {
            let cls = "quiz-option";
            if (checked && question.answer.kind === "mcq") {
              if (i === question.answer.correct_option) cls += " correct";
              else if (String(i) === selected) cls += " incorrect";
            }
            return (
              <button
                key={i}
                className={cls}
                disabled={checked}
                onClick={() => check(String(i))}
              >
                {opt}
              </button>
            );
          })}
        </div>
      )}

      {question.qtype === "tf" && (
        <div className="quiz-options tf">
          {["true", "false"].map((v) => {
            let cls = "quiz-option";
            if (checked && question.answer.kind === "tf") {
              if ((v === "true") === question.answer.value) cls += " correct";
              else if (v === selected) cls += " incorrect";
            }
            return (
              <button
                key={v}
                className={cls}
                disabled={checked}
                onClick={() => check(v)}
              >
                {v === "true" ? "True" : "False"}
              </button>
            );
          })}
        </div>
      )}

      {(question.qtype === "short" || question.qtype === "identification") &&
        !checked && (
          <form
            className="quiz-short"
            onSubmit={(e) => {
              e.preventDefault();
              setChecked(true);
            }}
          >
            <input
              className="input"
              value={shortInput}
              onChange={(e) => setShortInput(e.target.value)}
              placeholder={
                question.qtype === "identification"
                  ? "Name the term…"
                  : "Your answer…"
              }
              autoFocus
            />
            <button className="btn btn-primary">Check</button>
          </form>
        )}

      {question.qtype === "enumeration" && !checked && (
        <form
          className="quiz-short quiz-open"
          onSubmit={(e) => {
            e.preventDefault();
            setChecked(true);
          }}
        >
          <textarea
            className="input quiz-textarea"
            rows={4}
            value={enumInput}
            onChange={(e) => setEnumInput(e.target.value)}
            placeholder="One item per line…"
            autoFocus
          />
          <button className="btn btn-primary">Check</button>
        </form>
      )}

      {question.qtype === "essay" && !checked && (
        <form
          className="quiz-short quiz-open"
          onSubmit={(e) => {
            e.preventDefault();
            setChecked(true);
          }}
        >
          <textarea
            className="input quiz-textarea"
            rows={5}
            value={longInput}
            onChange={(e) => setLongInput(e.target.value)}
            placeholder="Write your answer…"
            autoFocus
          />
          <button className="btn btn-primary">Submit</button>
        </form>
      )}

      {(question.qtype === "coding" || question.qtype === "output") &&
        !checked && (
          <form
            className="quiz-short quiz-open"
            onSubmit={(e) => {
              e.preventDefault();
              setChecked(true);
            }}
          >
            <textarea
              className="input quiz-textarea quiz-code"
              rows={question.qtype === "coding" ? 6 : 3}
              value={longInput}
              onChange={(e) => setLongInput(e.target.value)}
              placeholder={
                question.qtype === "coding"
                  ? "Write your code…"
                  : "Exact output…"
              }
              spellCheck={false}
              autoFocus
            />
            <button className="btn btn-primary">
              {question.qtype === "coding" ? "Submit" : "Check"}
            </button>
          </form>
        )}

      {checked && (
        <div className="quiz-feedback">
          {(question.answer.kind === "mcq" || question.answer.kind === "tf") && (
            <p className={correctResponse ? "quiz-right" : "quiz-wrong"}>
              {correctResponse ? "Correct" : "Not quite"}
            </p>
          )}
          {verdict !== null && (
            <p className={verdict ? "quiz-right" : "quiz-wrong"}>
              {verdict ? "Correct" : "Not quite"}
            </p>
          )}

          {(question.answer.kind === "short" ||
            question.answer.kind === "identification") && (
            <>
              <p className="quiz-model-answer">
                <strong>Answer:</strong> {question.answer.text}
              </p>
              {shortInput && (
                <p className="quiz-your-answer">Yours: {shortInput}</p>
              )}
            </>
          )}
          {question.answer.kind === "enumeration" && enumHits && (
            <div className="quiz-enum-list">
              {question.answer.items.map((item, i) => (
                <span
                  key={i}
                  className={`quiz-enum-item ${enumHits[i] ? "hit" : "miss"}`}
                >
                  {item}
                </span>
              ))}
            </div>
          )}
          {question.answer.kind === "essay" && (
            <>
              <p className="quiz-model-answer">
                <strong>Model answer</strong>
              </p>
              <Markdown className="quiz-explanation">
                {question.answer.model_answer}
              </Markdown>
              {question.answer.key_points.length > 0 && (
                <ul className="quiz-key-points">
                  {question.answer.key_points.map((k, i) => (
                    <li key={i}>{k}</li>
                  ))}
                </ul>
              )}
            </>
          )}
          {question.answer.kind === "coding" && (
            <>
              <p className="quiz-model-answer">
                <strong>Reference solution</strong>
              </p>
              <Markdown className="quiz-explanation">
                {question.answer.solution}
              </Markdown>
            </>
          )}
          {question.answer.kind === "output" && (
            <>
              <p className="quiz-model-answer">
                <strong>Expected output</strong>
              </p>
              <pre className="quiz-output-block">{question.answer.text}</pre>
              {longInput && (
                <>
                  <p className="quiz-your-answer">Yours:</p>
                  <pre className="quiz-output-block">{longInput}</pre>
                </>
              )}
            </>
          )}
          {question.explanation && (
            <Markdown className="quiz-explanation">{question.explanation}</Markdown>
          )}
          <div className="quiz-sources">
            {question.citations.map((c) => (
              <CitationPill key={c.id} citation={c} />
            ))}
            {quiz.generation_mode === "exercise" &&
              question.citations.length === 0 && (
                <span
                  className="badge stale"
                  title="AI-synthesized practice question — not cited from your materials"
                >
                  synthesized
                </span>
              )}
          </div>
          {SELF_GRADED.has(question.qtype) ? (
            <div className="quiz-self-grade">
              <button className="btn grade-wrong" onClick={() => next(false)}>
                I was wrong
              </button>
              <button className="btn grade-right" onClick={() => next(true)}>
                I was right
              </button>
            </div>
          ) : verdict !== null ? (
            <>
              <button className="btn btn-primary" onClick={() => next(verdict)}>
                Next <ChevronRight size={15} strokeWidth={2} />
              </button>
              <button
                className="link-btn quiz-override"
                onClick={() => next(!verdict)}
              >
                Actually, I was {verdict ? "wrong" : "right"}
              </button>
            </>
          ) : (
            <button
              className="btn btn-primary"
              onClick={() => next(correctResponse === true)}
            >
              Next <ChevronRight size={15} strokeWidth={2} />
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Tab ───────────────────────────────────────────────────────

export function QuizTab({
  moduleId,
  courseId,
}: {
  moduleId: string;
  courseId: string;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const aiOnline = useAiOnline();
  const [configuring, setConfiguring] = useState(false);
  const [types, setTypes] = useState<string[]>(["mcq", "tf", "short"]);
  const [count, setCount] = useState(10);
  const [scopeIds, setScopeIds] = useState<number[]>([Number(moduleId)]);
  const [playing, setPlaying] = useState<number | null>(null);
  const [docIds, setDocIds] = useState<number[] | null>(null);
  const [noteIds, setNoteIds] = useState<number[] | null>(null);
  const [instructions, setInstructions] = useState("");
  const [mode, setMode] = useState<GenerationMode>("sources");
  // Document/note narrowing only applies to a single-module quiz. An empty
  // document scope blocks generation, except practice mode with a focus
  // topic (synthesizes from nothing).
  const singleModule = scopeIds.length === 1;
  const noSources = singleModule && docIds !== null && docIds.length === 0;
  const topicOnly = mode === "exercise" && instructions.trim().length > 0;
  const blocked = noSources && !topicOnly;

  const quizzes = useQuery({
    queryKey: ["quizzes", moduleId],
    queryFn: () => api.get<QuizListItem[]>(`/api/modules/${moduleId}/quizzes`),
  });

  const modules = useQuery({
    queryKey: ["modules", courseId],
    queryFn: () => api.get<ModuleOut[]>(`/api/courses/${courseId}/modules`),
    enabled: configuring,
  });

  const activeQuiz = useQuery({
    queryKey: ["quiz", playing],
    queryFn: () => api.get<QuizOut>(`/api/quizzes/${playing}`),
    enabled: playing != null,
  });

  const gen = useGenerationJob(moduleId, "generate_quiz", () => {
    queryClient.invalidateQueries({ queryKey: ["quizzes", moduleId] });
    setConfiguring(false);
  });

  const create = useMutation({
    mutationFn: () =>
      api.post<JobRef>("/api/quizzes", {
        module_ids: scopeIds,
        types,
        count,
        document_ids: singleModule ? docIds : null,
        note_ids: singleModule ? noteIds : null,
        instructions: instructions.trim() || null,
        mode,
      }),
    onSuccess: (ref) => gen.start(ref.job_id),
  });

  function toggleType(t: string) {
    setTypes((prev) =>
      prev.includes(t)
        ? prev.length > 1
          ? prev.filter((x) => x !== t)
          : prev
        : [...prev, t],
    );
  }

  function toggleScope(id: number) {
    setScopeIds((prev) => {
      const next = prev.includes(id)
        ? prev.length > 1
          ? prev.filter((x) => x !== id)
          : prev
        : [...prev, id];
      // Material narrowing is per-module; reset it when the module set changes.
      if (next.length !== 1 || next[0] !== prev[0]) {
        setDocIds(null);
        setNoteIds(null);
      }
      return next;
    });
  }

  if (playing != null && activeQuiz.data) {
    return (
      <QuizPlayer
        quiz={activeQuiz.data}
        onExit={() => setPlaying(null)}
        onDebrief={(missed) => {
          const list = missed
            .slice(0, 6)
            .map((q, i) => `${i + 1}. ${q}`)
            .join(" ");
          navigate({
            to: "/courses/$courseId/modules/$moduleId",
            params: { courseId, moduleId },
            search: {
              tab: "chat",
              ask: `I just took a quiz and missed these questions: ${list} — debrief me: why are the right answers right, and what am I misunderstanding?`,
            },
          });
        }}
      />
    );
  }

  return (
    <div className="quiz-tab">
      <header className="gen-head">
        <span className="gen-head-meta">
          {quizzes.data?.length ?? 0} quiz{(quizzes.data?.length ?? 0) === 1 ? "" : "zes"}
        </span>
        <span className="gen-head-spacer" />
        <button
          className="btn btn-primary"
          onClick={() => setConfiguring((v) => !v)}
          disabled={gen.running}
        >
          <Plus size={15} strokeWidth={2} /> New quiz
        </button>
      </header>

      {!aiOnline && gen.running && <AiOfflineBanner />}
      {gen.running && <JobProgress job={gen.job} />}
      {gen.job?.status === "failed" && (
        <p className="error-text">Generation failed: {gen.job.error}</p>
      )}
      {create.isError && (
        <p className="error-text">{(create.error as Error).message}</p>
      )}

      {configuring && !gen.running && (
        <div className="quiz-config">
          <div className="quiz-config-row">
            <span className="field-label">Scope</span>
            <div className="quiz-scope">
              {(modules.data ?? []).map((m) => (
                <label key={m.id} className="quiz-check">
                  <input
                    type="checkbox"
                    checked={scopeIds.includes(m.id)}
                    onChange={() => toggleScope(m.id)}
                  />
                  {m.title}
                </label>
              ))}
            </div>
          </div>
          <div className="quiz-config-row">
            <span className="field-label">Question types</span>
            <div className="quiz-scope">
              {Object.entries(TYPE_LABELS).map(([t, label]) => (
                <label key={t} className="quiz-check">
                  <input
                    type="checkbox"
                    checked={types.includes(t)}
                    onChange={() => toggleType(t)}
                  />
                  {label}
                </label>
              ))}
            </div>
          </div>
          <div className="quiz-config-row">
            <span className="field-label">Materials</span>
            {singleModule ? (
              <SourcesPicker
                moduleId={String(scopeIds[0])}
                documentIds={docIds}
                noteIds={noteIds}
                onChange={(d, n) => {
                  setDocIds(d);
                  setNoteIds(n);
                }}
              />
            ) : (
              <span className="gen-hint quiz-scope-hint">
                Pick a single module to narrow sources.
              </span>
            )}
          </div>
          <div className="quiz-config-row">
            <span className="field-label">Style</span>
            <div className="mode-toggle">
              <button
                type="button"
                className={`btn${mode === "sources" ? " active" : ""}`}
                onClick={() => setMode("sources")}
                title="Questions cite the exact passages they come from"
              >
                From sources (cited)
              </button>
              <button
                type="button"
                className={`btn${mode === "exercise" ? " active" : ""}`}
                onClick={() => setMode("exercise")}
                title="Original practice exercises on the materials' topics — answers are AI-derived, not cited"
              >
                Practice exercises
              </button>
            </div>
          </div>
          <div className="quiz-config-row">
            <span className="field-label">Focus</span>
            <textarea
              className="input quiz-instructions"
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              rows={2}
              placeholder="Optional — e.g. a quiz on C increment/decrement operators"
            />
          </div>
          <div className="quiz-config-row">
            <span className="field-label">Questions</span>
            <select
              className="input quiz-count"
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
            >
              {[5, 10, 15, 20].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
          {blocked && (
            <p className="gen-hint">
              {mode === "exercise"
                ? "Add a focus topic to generate practice questions without source documents."
                : "Select at least one document — or switch to Practice exercises with a focus topic to generate without sources."}
            </p>
          )}
          <button
            className="btn btn-primary"
            onClick={() => create.mutate()}
            disabled={create.isPending || blocked}
          >
            <ListChecks size={15} strokeWidth={1.75} /> Generate quiz
          </button>
        </div>
      )}

      {quizzes.data && quizzes.data.length === 0 && !configuring && !gen.running && (
        <div className="gen-empty">
          <p>
            No quizzes yet. Generate source-grounded questions from this module
            — or span several modules for exam practice.
          </p>
        </div>
      )}

      <div className="quiz-list">
        {(quizzes.data ?? []).map((q) => (
          <button key={q.artifact_id} className="quiz-item" onClick={() => setPlaying(q.artifact_id)}>
            <span className="quiz-item-title">
              {q.title}
              {q.generation_mode === "exercise" && (
                <span className="badge deck-pill">practice</span>
              )}
            </span>
            <span className="quiz-item-meta">
              {q.question_count} questions
              {q.attempt_count > 0 && ` · best ${q.best_score ?? 0}%`}
              {" · "}
              {new Date(q.generated_at).toLocaleDateString()}
            </span>
            <ChevronRight size={16} strokeWidth={1.5} />
          </button>
        ))}
      </div>
    </div>
  );
}
