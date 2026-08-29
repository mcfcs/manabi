import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import {
  ChevronLeft,
  ChevronRight,
  Flag,
  ListChecks,
  Loader2,
  Plus,
  RefreshCw,
  SkipForward,
} from "lucide-react";
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
  useJob,
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
  // "skip" is excluded from the score entirely (not counted as wrong)
  const [results, setResults] = useState<("right" | "wrong" | "skip")[]>([]);
  const [attemptId, setAttemptId] = useState<number | null>(null);
  const [responses, setResponses] = useState<Record<string, unknown>>({});
  // Per-question input snapshots so answered questions can be revisited
  // (review-only — outcomes are final once graded).
  type Snapshot = {
    selected: string | null;
    shortInput: string;
    enumInput: string;
    longInput: string;
  };
  const [answered, setAnswered] = useState<Snapshot[]>([]);
  // Stashes the in-progress (frontier) question's inputs while reviewing.
  const draftRef = useRef<(Snapshot & { checked: boolean }) | null>(null);
  const reviewing = index < results.length;

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

  function typedAnswerFor(q: QuestionOut): string {
    if (q.qtype === "mcq")
      return selected != null && q.options
        ? (q.options[Number(selected)] ?? "")
        : "";
    if (q.qtype === "tf") return selected ?? "";
    if (q.qtype === "enumeration") return enumInput;
    if (q.qtype === "essay" || q.qtype === "coding" || q.qtype === "output")
      return longInput;
    return shortInput;
  }

  function finishQuestion(outcome: "right" | "wrong" | "skip") {
    const q = question!;
    const typed =
      q.qtype === "enumeration"
        ? enumInput
        : q.qtype === "essay" || q.qtype === "coding" || q.qtype === "output"
          ? longInput
          : shortInput;
    const newResults = [...results, outcome];
    const newResponses = {
      ...responses,
      [q.id]: outcome === "skip" ? "(skipped)" : (selected ?? typed),
    };
    setResults(newResults);
    setResponses(newResponses);
    setAnswered([...answered, { selected, shortInput, enumInput, longInput }]);
    setChecked(false);
    setSelected(null);
    setShortInput("");
    setEnumInput("");
    setLongInput("");
    setChallengeJobId(null);
    setIndex((i) => i + 1);
    const done = index + 1 >= quiz.questions.length;
    if (attemptId != null) {
      const answered = newResults.filter((r) => r !== "skip").length;
      const right = newResults.filter((r) => r === "right").length;
      const score = answered ? right / answered : 0;
      api
        .patch(`/api/quiz-attempts/${attemptId}`, {
          responses: newResponses,
          score: done ? Math.round(score * 1000) / 10 : null,
          finished: done,
        })
        .catch(() => undefined);
    }
  }

  function next(correct: boolean) {
    finishQuestion(correct ? "right" : "wrong");
  }

  // ── Review navigation (Previous / back to current) ──────────────────
  function restoreSnapshot(s: Snapshot) {
    setSelected(s.selected);
    setShortInput(s.shortInput);
    setEnumInput(s.enumInput);
    setLongInput(s.longInput);
  }

  function goPrev() {
    if (index === 0) return;
    if (!reviewing) {
      // leaving the live question — stash its inputs so nothing is lost
      draftRef.current = { selected, shortInput, enumInput, longInput, checked };
    }
    restoreSnapshot(answered[index - 1]);
    setChecked(true);
    setChallengeJobId(null);
    setIndex(index - 1);
  }

  function goForward() {
    const nextIdx = index + 1;
    setChallengeJobId(null);
    if (nextIdx < results.length) {
      restoreSnapshot(answered[nextIdx]);
      setChecked(true);
    } else {
      const d = draftRef.current;
      restoreSnapshot(
        d ?? { selected: null, shortInput: "", enumInput: "", longInput: "" },
      );
      setChecked(d?.checked ?? false);
      draftRef.current = null;
    }
    setIndex(nextIdx);
  }

  // ── "Think this answer is wrong?" — AI adjudication ─────────────────
  const [challengeJobId, setChallengeJobId] = useState<number | null>(null);
  const challengeJob = useJob(challengeJobId);
  const disputeVerdict =
    challengeJobId != null && challengeJob.data?.status === "succeeded"
      ? ((challengeJob.data.result?.verdict ?? null) as {
          stored_answer_correct: boolean;
          user_answer_correct: boolean;
          explanation: string;
          corrected_answer: string;
        } | null)
      : null;
  const challenge = useMutation({
    mutationFn: () =>
      api.post<JobRef>(`/api/quiz-questions/${question!.id}/challenge`, {
        user_answer: typedAnswerFor(question!),
      }),
    onSuccess: (r) => setChallengeJobId(r.job_id),
  });
  const challengePending =
    challenge.isPending ||
    (challengeJobId != null &&
      disputeVerdict == null &&
      challengeJob.data?.status !== "failed");

  // ── Regenerate this question in place ───────────────────────────────
  const queryClient = useQueryClient();
  const [regenJobId, setRegenJobId] = useState<number | null>(null);
  const regenJob = useJob(regenJobId);
  const regen = useMutation({
    mutationFn: () =>
      api.post<JobRef>(`/api/quiz-questions/${question!.id}/regenerate`),
    onSuccess: (r) => setRegenJobId(r.job_id),
  });
  useEffect(() => {
    if (regenJobId != null && regenJob.data?.status === "succeeded") {
      setRegenJobId(null);
      setChecked(false);
      setSelected(null);
      setShortInput("");
      setEnumInput("");
      setLongInput("");
      setChallengeJobId(null);
      queryClient.invalidateQueries({ queryKey: ["quiz", quiz.artifact_id] });
    }
  }, [regenJobId, regenJob.data?.status, queryClient, quiz.artifact_id]);
  const regenPending =
    regen.isPending ||
    (regenJobId != null &&
      regenJob.data?.status !== "failed" &&
      regenJob.data?.status !== "succeeded");

  if (finished) {
    const right = results.filter((r) => r === "right").length;
    const answered = results.filter((r) => r !== "skip").length;
    const skipped = results.length - answered;
    const missed = quiz.questions
      .filter((_, i) => results[i] === "wrong")
      .map((q) => q.prompt);
    return (
      <div className="quiz-results">
        <h3>
          {right} / {answered}
        </h3>
        <p className="quiz-results-sub">
          {skipped > 0 &&
            `${skipped} skipped (not counted). `}
          {answered === 0
            ? "Nothing answered this round."
            : right === answered
              ? "Perfect score."
              : right >= answered * 0.7
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
        <span className="quiz-meta-actions">
          <button
            className="btn"
            onClick={goPrev}
            disabled={index === 0 || regenPending}
            title="Review the previous question"
          >
            <ChevronLeft size={15} strokeWidth={1.75} /> Previous
          </button>
          {!reviewing && (
            <>
              <button
                className="btn"
                onClick={() => finishQuestion("skip")}
                disabled={regenPending}
                title="Skip this question — it won't count toward your score"
              >
                <SkipForward size={15} strokeWidth={1.75} /> Skip
              </button>
              <button
                className="btn"
                onClick={() => regen.mutate()}
                disabled={regenPending}
                title="Replace this question with a freshly generated one"
              >
                <RefreshCw
                  size={15}
                  strokeWidth={1.75}
                  className={regenPending ? "spin" : ""}
                />{" "}
                Regenerate
              </button>
            </>
          )}
          <button className="btn" onClick={onExit}>
            Exit quiz
          </button>
        </span>
      </div>

      {reviewing && (
        <p className="quiz-pending-line">
          Reviewing an answered question — its result is locked in.
        </p>
      )}

      {regenPending && (
        <p className="quiz-pending-line">
          <Loader2 size={13} className="spin" /> Writing a replacement
          question…
        </p>
      )}
      {regenJobId != null && regenJob.data?.status === "failed" && (
        <p className="error-text">
          Regeneration failed: {regenJob.data.error}
        </p>
      )}

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
          {reviewing && (
            <p
              className={
                results[index] === "right"
                  ? "quiz-right"
                  : results[index] === "wrong"
                    ? "quiz-wrong"
                    : "quiz-pending-line"
              }
            >
              {results[index] === "right"
                ? "You got this right"
                : results[index] === "wrong"
                  ? "You got this wrong"
                  : "You skipped this one"}
            </p>
          )}
          {!reviewing &&
            (question.answer.kind === "mcq" ||
              question.answer.kind === "tf") && (
              <p className={correctResponse ? "quiz-right" : "quiz-wrong"}>
                {correctResponse ? "Correct" : "Not quite"}
              </p>
            )}
          {!reviewing && verdict !== null && (
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

          <div className="quiz-dispute">
            {challengeJobId == null && !challenge.isPending && (
              <button
                className="link-btn"
                onClick={() => challenge.mutate()}
                title="The AI re-derives the answer against the cited sources and says who is right"
              >
                <Flag size={13} strokeWidth={1.75} /> Think this answer is
                wrong? Check with AI
              </button>
            )}
            {challengePending && (
              <p className="quiz-pending-line">
                <Loader2 size={13} className="spin" /> Double-checking against
                the sources…
              </p>
            )}
            {challengeJobId != null &&
              challengeJob.data?.status === "failed" && (
                <p className="error-text">
                  Check failed: {challengeJob.data.error}
                </p>
              )}
            {disputeVerdict && (
              <div
                className={`quiz-verdict ${
                  disputeVerdict.stored_answer_correct ? "upheld" : "overturned"
                }`}
              >
                <strong>
                  {!disputeVerdict.stored_answer_correct &&
                  disputeVerdict.user_answer_correct
                    ? "You were right — the generated answer is wrong"
                    : !disputeVerdict.stored_answer_correct
                      ? "The generated answer is wrong (yours has issues too)"
                      : disputeVerdict.user_answer_correct
                        ? "Both answers check out"
                        : "The generated answer stands"}
                </strong>
                {disputeVerdict.explanation && <p>{disputeVerdict.explanation}</p>}
                {disputeVerdict.corrected_answer && (
                  <p>
                    <strong>Correct answer:</strong>{" "}
                    {disputeVerdict.corrected_answer}
                  </p>
                )}
                {!disputeVerdict.stored_answer_correct && (
                  <button
                    className="link-btn"
                    onClick={() => regen.mutate()}
                    disabled={regenPending}
                  >
                    <RefreshCw size={13} strokeWidth={1.75} /> Regenerate this
                    question
                  </button>
                )}
              </div>
            )}
          </div>
          {reviewing ? (
            <button className="btn btn-primary" onClick={goForward}>
              {index + 1 < results.length ? "Next" : "Back to current"}{" "}
              <ChevronRight size={15} strokeWidth={2} />
            </button>
          ) : SELF_GRADED.has(question.qtype) ? (
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
