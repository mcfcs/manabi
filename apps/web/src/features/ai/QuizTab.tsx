import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, ListChecks, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  api,
  type JobRef,
  type ModuleOut,
  type QuestionOut,
  type QuizListItem,
  type QuizOut,
} from "../../lib/api";
import {
  AiOfflineBanner,
  CitationPill,
  JobProgress,
  useAiOnline,
  useGenerationJob,
} from "./common";
import "./quiz.css";

const TYPE_LABELS: Record<string, string> = {
  mcq: "Multiple choice",
  tf: "True / False",
  short: "Short answer",
};

// ── Taking a quiz ─────────────────────────────────────────────

function QuizPlayer({ quiz, onExit }: { quiz: QuizOut; onExit: () => void }) {
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const [shortInput, setShortInput] = useState("");
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
    const newResults = [...results, correct];
    const newResponses = { ...responses, [q.id]: selected ?? shortInput };
    setResults(newResults);
    setResponses(newResponses);
    setChecked(false);
    setSelected(null);
    setShortInput("");
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
        <button className="btn btn-primary" onClick={onExit}>
          Back to quizzes
        </button>
      </div>
    );
  }
  if (!question) return null;

  const correctResponse =
    checked && selected !== null && question.answer.kind !== "short"
      ? isCorrect(question, selected)
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

      <p className="quiz-question">{question.prompt}</p>

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

      {question.qtype === "short" && !checked && (
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
            placeholder="Your answer…"
            autoFocus
          />
          <button className="btn btn-primary">Check</button>
        </form>
      )}

      {checked && (
        <div className="quiz-feedback">
          {question.qtype === "short" ? (
            <>
              <p className="quiz-model-answer">
                <strong>Answer:</strong>{" "}
                {question.answer.kind === "short" ? question.answer.text : ""}
              </p>
              {shortInput && (
                <p className="quiz-your-answer">Yours: {shortInput}</p>
              )}
            </>
          ) : (
            <p className={correctResponse ? "quiz-right" : "quiz-wrong"}>
              {correctResponse ? "Correct" : "Not quite"}
            </p>
          )}
          {question.explanation && (
            <p className="quiz-explanation">{question.explanation}</p>
          )}
          <div className="quiz-sources">
            {question.citations.map((c) => (
              <CitationPill key={c.id} citation={c} />
            ))}
          </div>
          {question.qtype === "short" ? (
            <div className="quiz-self-grade">
              <button className="btn grade-wrong" onClick={() => next(false)}>
                I was wrong
              </button>
              <button className="btn grade-right" onClick={() => next(true)}>
                I was right
              </button>
            </div>
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
  const aiOnline = useAiOnline();
  const [configuring, setConfiguring] = useState(false);
  const [types, setTypes] = useState<string[]>(["mcq", "tf", "short"]);
  const [count, setCount] = useState(10);
  const [scopeIds, setScopeIds] = useState<number[]>([Number(moduleId)]);
  const [playing, setPlaying] = useState<number | null>(null);

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
      api.post<JobRef>("/api/quizzes", { module_ids: scopeIds, types, count }),
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
    setScopeIds((prev) =>
      prev.includes(id)
        ? prev.length > 1
          ? prev.filter((x) => x !== id)
          : prev
        : [...prev, id],
    );
  }

  if (playing != null && activeQuiz.data) {
    return <QuizPlayer quiz={activeQuiz.data} onExit={() => setPlaying(null)} />;
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
          <button
            className="btn btn-primary"
            onClick={() => create.mutate()}
            disabled={create.isPending}
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
            <span className="quiz-item-title">{q.title}</span>
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
