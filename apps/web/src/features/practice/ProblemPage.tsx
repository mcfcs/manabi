import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import {
  BadgeCheck,
  Check,
  ChevronLeft,
  Eye,
  History,
  Lightbulb,
  Loader2,
  Play,
  Send,
  Trash2,
  X,
} from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  api,
  type CodeSample,
  type CodeVerdict,
  type PracticeLanguage,
  type PracticeVerdict,
  type ProblemOut,
  type SubmissionOut,
  type TestResult,
  type TheorySample,
  type TheoryVerdict,
} from "../../lib/api";
import { ProgressNote } from "./PracticePage";
import { StatementMarkdown as Markdown } from "./StatementMarkdown";
import {
  asText,
  initialCode,
  isActive,
  KIND_LABEL,
  LANG_LABEL,
  LANGS,
  loadDraft,
  saveDraft,
  showString,
  timeAgo,
  verdictLabel,
  verdictTone,
} from "./shared";
import "./practice.css";

const CodeEditor = lazy(() => import("./CodeEditor"));

const FORMAT_HELP: Record<"grammar" | "regex" | "dfa", { example: string; notes: string[] }> = {
  grammar: {
    example: "S -> a S b | ε",
    notes: [
      "One nonterminal per line, with its alternatives after ->.",
      "Separate alternatives with |; write ε for the empty string.",
      "Separate symbols with spaces. The first line's nonterminal is the start symbol.",
    ],
  },
  regex: {
    example: "(a|b)*abb",
    notes: [
      "Concatenate by writing symbols side by side.",
      "| for union, * zero or more, + one or more, ? optional, ( ) to group.",
      "ε matches the empty string.",
    ],
  },
  dfa: {
    example: "start: q0\naccept: q2\nq0 a q1\nq1 b q2",
    notes: [
      "start: names the start state; accept: lists the accepting states.",
      "Then one transition per line: state symbol next-state.",
      "A missing transition rejects the string.",
    ],
  },
};

// ── Statement column ───────────────────────────────────────────────────

function Pre({ text, className }: { text: string; className?: string }) {
  return <pre className={`practice-pre${className ? ` ${className}` : ""}`}>{text === "" ? " " : text}</pre>;
}

function CodeStatement({ problem }: { problem: ProblemOut }) {
  const spec = problem.spec ?? {};
  const samples = (problem.samples as CodeSample[]).filter((s) => s && typeof s.input === "string");
  const sections: [string, string][] = [
    ["Input format", asText(spec.input_format)],
    ["Output format", asText(spec.output_format)],
    ["Constraints", asText(spec.constraints)],
  ];
  return (
    <>
      {sections
        .filter(([, body]) => body.trim())
        .map(([title, body]) => (
          <section key={title} className="practice-sec">
            <h3>{title}</h3>
            <Markdown className="practice-md">{body}</Markdown>
          </section>
        ))}
      {samples.length > 0 && (
        <section className="practice-sec">
          <h3>Sample tests</h3>
          <ol className="practice-samples">
            {samples.map((s, i) => (
              <li key={i} className="practice-sample">
                <span className="practice-sample-n">Sample {i + 1}</span>
                <div className="practice-io">
                  <div>
                    <span className="practice-io-label">Input</span>
                    <Pre text={s.input} />
                  </div>
                  <div>
                    <span className="practice-io-label">Expected output</span>
                    <Pre text={s.output} />
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}
      <p className="study-muted study-small">
        Time limit {problem.time_limit_ms >= 1000 ? `${problem.time_limit_ms / 1000} s` : `${problem.time_limit_ms} ms`}{" "}
        per test · {problem.test_count} hidden test{problem.test_count === 1 ? "" : "s"}
      </p>
    </>
  );
}

function TheoryStatement({ problem }: { problem: ProblemOut }) {
  const spec = problem.spec ?? {};
  const alphabet = Array.isArray(spec.alphabet) ? spec.alphabet : [];
  const samples = (problem.samples as TheorySample[]).filter((s) => s && typeof s.s === "string");
  const accepted = samples.filter((s) => s.accept);
  const rejected = samples.filter((s) => !s.accept);
  const help = FORMAT_HELP[problem.kind as "grammar" | "regex" | "dfa"];
  return (
    <>
      {alphabet.length > 0 && (
        <section className="practice-sec">
          <h3>Alphabet</h3>
          <p className="practice-alphabet mono">
            Σ = {"{"} {alphabet.join(", ")} {"}"}
          </p>
        </section>
      )}
      {samples.length > 0 && (
        <section className="practice-sec">
          <h3>Example strings</h3>
          <div className="practice-examples">
            <div>
              <span className="practice-io-label">Accepted</span>
              <ul>
                {accepted.map((s, i) => (
                  <li key={i} className="practice-ex ok">
                    <Check size={13} strokeWidth={2.5} aria-label="accepted" />
                    <code>{showString(s.s)}</code>
                  </li>
                ))}
                {accepted.length === 0 && <li className="study-muted study-small">none shown</li>}
              </ul>
            </div>
            <div>
              <span className="practice-io-label">Rejected</span>
              <ul>
                {rejected.map((s, i) => (
                  <li key={i} className="practice-ex bad">
                    <X size={13} strokeWidth={2.5} aria-label="rejected" />
                    <code>{showString(s.s)}</code>
                  </li>
                ))}
                {rejected.length === 0 && <li className="study-muted study-small">none shown</li>}
              </ul>
            </div>
          </div>
        </section>
      )}
      {asText(spec.hint).trim() && (
        <details className="practice-hint">
          <summary>
            <Lightbulb size={14} strokeWidth={1.75} /> Show hint
          </summary>
          <Markdown className="practice-md">{asText(spec.hint)}</Markdown>
        </details>
      )}
      {help && (
        <section className="practice-format">
          <h3>Answer format</h3>
          <Pre text={help.example} />
          <ul>
            {help.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

// ── Results ────────────────────────────────────────────────────────────

function TestDetail({ r, hidden }: { r: TestResult; hidden?: boolean }) {
  const tone = verdictTone(r.verdict);
  return (
    <li className={`practice-test ${tone}`}>
      <div className="practice-test-head">
        <span className={`practice-test-dot ${tone}`} aria-hidden />
        <strong>
          {hidden ? "Hidden test" : "Test"} {r.index + 1}
        </strong>
        <span className={`practice-tone ${tone}`}>{verdictLabel(r.verdict)}</span>
        <span className="study-muted study-small mono">{r.ms} ms</span>
      </div>
      {r.verdict !== "passed" && (
        <>
          <div className="practice-io practice-io-3">
            <div>
              <span className="practice-io-label">Input</span>
              <Pre text={r.input ?? ""} />
            </div>
            <div>
              <span className="practice-io-label">Expected</span>
              <Pre text={r.expected ?? ""} />
            </div>
            <div>
              <span className="practice-io-label">Your output</span>
              <Pre text={r.got ?? ""} className={r.verdict === "wrong" ? "diff" : ""} />
            </div>
          </div>
          {r.error && <Pre text={r.error} className="practice-pre-error" />}
        </>
      )}
    </li>
  );
}

function CodeResults({ v, mode }: { v: CodeVerdict; mode: "run" | "submit" }) {
  const [openPassed, setOpenPassed] = useState(false);
  if (v.verdict === "compile_error") {
    return <Pre text={v.compile_error || "The compiler reported an error."} className="practice-pre-error" />;
  }
  if (mode === "submit") {
    return (
      <>
        <div className="practice-dots" aria-label={`${v.passed} of ${v.total} hidden tests passed`}>
          {v.results.map((r) => (
            <span
              key={r.index}
              className={`practice-dot-test ${verdictTone(r.verdict)}`}
              title={`Test ${r.index + 1}: ${verdictLabel(r.verdict)} (${r.ms} ms)`}
            />
          ))}
        </div>
        {v.first_failure && (
          <>
            <p className="practice-res-note">First failing test:</p>
            <ul className="practice-tests">
              <TestDetail r={v.first_failure} hidden />
            </ul>
          </>
        )}
      </>
    );
  }
  const failing = v.results.filter((r) => r.verdict !== "passed");
  const passing = v.results.filter((r) => r.verdict === "passed");
  return (
    <ul className="practice-tests">
      {failing.map((r) => (
        <TestDetail key={r.index} r={r} />
      ))}
      {passing.length > 0 && (failing.length === 0 || openPassed)
        ? passing.map((r) => <PassedTest key={r.index} r={r} />)
        : passing.length > 0 && (
            <li>
              <button type="button" className="link-btn" onClick={() => setOpenPassed(true)}>
                Show {passing.length} passing test{passing.length === 1 ? "" : "s"}
              </button>
            </li>
          )}
    </ul>
  );
}

/** A passing RUN test: collapsed to one line, its I/O one click away. */
function PassedTest({ r }: { r: TestResult }) {
  return (
    <li className="practice-test ok">
      <details>
        <summary className="practice-test-head">
          <span className="practice-test-dot ok" aria-hidden />
          <strong>Test {r.index + 1}</strong>
          <span className="practice-tone ok">Passed</span>
          <span className="study-muted study-small mono">{r.ms} ms</span>
        </summary>
        <div className="practice-io">
          <div>
            <span className="practice-io-label">Input</span>
            <Pre text={r.input ?? ""} />
          </div>
          <div>
            <span className="practice-io-label">Your output</span>
            <Pre text={r.got ?? ""} />
          </div>
        </div>
      </details>
    </li>
  );
}

function TheoryResults({ v }: { v: TheoryVerdict }) {
  if (v.verdict === "format_error") {
    return <Pre text={v.compile_error || "The answer could not be read."} className="practice-pre-error" />;
  }
  return (
    <>
      {v.mismatches.length > 0 && (
        <ul className="practice-mismatches">
          {v.mismatches.map((m, i) => (
            <li key={i}>
              {m.expected ? (
                <Check size={14} strokeWidth={2.5} className="ok" aria-hidden />
              ) : (
                <X size={14} strokeWidth={2.5} className="bad" aria-hidden />
              )}
              <span>
                <code>{showString(m.string)}</code> should be {m.expected ? "accepted" : "rejected"}
              </span>
            </li>
          ))}
        </ul>
      )}
      {v.max_len > 0 && (
        <p className="study-muted study-small">Checked every string up to length {v.max_len}.</p>
      )}
    </>
  );
}

function Results({
  result,
  kind,
}: {
  result: { mode: "run" | "submit"; v: PracticeVerdict };
  kind: ProblemOut["kind"];
}) {
  const { mode, v } = result;
  const tone = verdictTone(v.verdict);
  const showCount = v.verdict !== "compile_error" && v.verdict !== "format_error";
  return (
    <section className="practice-results" aria-live="polite">
      <div className={`practice-verdict ${tone}`}>
        <span className="practice-verdict-label">
          {v.verdict === "accepted" ? <BadgeCheck size={18} strokeWidth={2} /> : <X size={18} strokeWidth={2} />}
          {verdictLabel(v.verdict)}
        </span>
        <span className="practice-verdict-meta">
          {mode === "run" ? "Samples" : "Hidden tests"}
          {showCount && (
            <>
              {" · "}passed <strong>{v.passed}</strong> / {v.total}
            </>
          )}
        </span>
      </div>
      {mode === "submit" && v.verdict === "accepted" && (
        <p className="practice-res-note ok">Every hidden test passed — this problem is solved.</p>
      )}
      {mode === "run" && v.verdict === "accepted" && (
        <p className="practice-res-note">The samples pass. Submit to run the hidden tests.</p>
      )}
      {kind === "code" ? <CodeResults v={v as CodeVerdict} mode={mode} /> : <TheoryResults v={v as TheoryVerdict} />}
    </section>
  );
}

// ── Page ───────────────────────────────────────────────────────────────

function EditorFallback({ compact }: { compact: boolean }) {
  return (
    <div className={`practice-cm practice-cm-loading${compact ? " compact" : ""}`}>
      <Loader2 size={14} className="spin" /> Loading the editor
    </div>
  );
}

function Workspace({ problem }: { problem: ProblemOut }) {
  const qc = useQueryClient();
  const isCode = problem.kind === "code";
  const [lang, setLang] = useState<PracticeLanguage>(problem.language ?? "c");
  // One draft per language (code) or one for the answer (theory).
  const slot = isCode ? lang : problem.kind;
  const [drafts, setDrafts] = useState<Record<string, string>>(() =>
    isCode
      ? { [lang]: initialCode(problem, lang) }
      : { [problem.kind]: loadDraft(problem.id, problem.kind) ?? "" },
  );
  const text = drafts[slot] ?? "";
  const [result, setResult] = useState<{ mode: "run" | "submit"; v: PracticeVerdict } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const saveTimer = useRef<number | undefined>(undefined);
  const setText = useCallback(
    (v: string) => {
      setDrafts((d) => ({ ...d, [slot]: v }));
      window.clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(() => saveDraft(problem.id, slot, v), 300);
    },
    [problem.id, slot],
  );

  function switchLang(next: PracticeLanguage) {
    // flush the pending save for the language we are leaving
    window.clearTimeout(saveTimer.current);
    saveDraft(problem.id, lang, text);
    setDrafts((d) => (d[next] != null ? d : { ...d, [next]: initialCode(problem, next) }));
    setLang(next);
  }

  const submissions = useQuery({
    queryKey: ["practice-submissions", problem.id],
    queryFn: () => api.get<SubmissionOut[]>(`/api/practice/problems/${problem.id}/submissions`),
  });

  const judge = useMutation({
    mutationFn: async (mode: "run" | "submit") => ({
      mode,
      v: await api.post<PracticeVerdict>(`/api/practice/problems/${problem.id}/${mode}`, {
        answer: text,
        ...(isCode ? { language: lang } : {}),
      }),
    }),
    onSuccess: (r) => {
      setError(null);
      setResult(r);
      qc.invalidateQueries({ queryKey: ["practice-submissions", problem.id] });
      if (r.mode === "submit") {
        qc.invalidateQueries({ queryKey: ["practice-problem", String(problem.id)] });
        qc.invalidateQueries({ queryKey: ["practice-problems"] });
      }
    },
    onError: (e) => setError((e as Error).message),
  });

  const busy = judge.isPending;
  const run = useCallback(() => {
    if (!busy && text.trim()) judge.mutate("run");
  }, [busy, text, judge]);

  // Ctrl/Cmd+Enter = Run anywhere on the page (the editor handles its own).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return;
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        run();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [run]);

  const reveal = useMutation({
    mutationFn: () => api.post<ProblemOut>(`/api/practice/problems/${problem.id}/reveal`),
    onSuccess: (p) => qc.setQueryData(["practice-problem", String(problem.id)], p),
  });

  function loadSubmission(s: SubmissionOut) {
    const target = isCode ? (s.language ?? lang) : problem.kind;
    if (isCode && s.language && s.language !== lang) {
      window.clearTimeout(saveTimer.current);
      saveDraft(problem.id, lang, text);
      setLang(s.language);
    }
    setDrafts((d) => ({ ...d, [target]: s.code }));
    saveDraft(problem.id, target, s.code);
  }

  const solutionLang = problem.language ? LANG_LABEL[problem.language] : KIND_LABEL[problem.kind];

  return (
    <div className="practice-work">
      <section className="practice-editor-card" aria-label="Your answer">
        <div className="practice-editor-bar">
          {isCode ? (
            <select
              className="input practice-lang"
              aria-label="Language"
              value={lang}
              onChange={(e) => switchLang(e.target.value as PracticeLanguage)}
            >
              {LANGS.map((l) => (
                <option key={l} value={l}>
                  {LANG_LABEL[l]}
                </option>
              ))}
            </select>
          ) : (
            <span className="practice-editor-title">Your {KIND_LABEL[problem.kind].toLowerCase()}</span>
          )}
          <span className="gen-hint practice-kbd-hint">
            <kbd>Ctrl</kbd>+<kbd>Enter</kbd> to run
          </span>
        </div>
        <Suspense fallback={<EditorFallback compact={!isCode} />}>
          <CodeEditor
            value={text}
            onChange={setText}
            language={isCode ? lang : null}
            onRun={run}
            compact={!isCode}
            ariaLabel={isCode ? `${LANG_LABEL[lang]} code` : `Your ${KIND_LABEL[problem.kind]} answer`}
          />
        </Suspense>
        <div className="practice-actions">
          <button
            type="button"
            className="btn"
            onClick={() => judge.mutate("run")}
            disabled={busy || !text.trim()}
            title="Judge on the sample tests (Ctrl/⌘ Enter)"
          >
            {busy && judge.variables === "run" ? <Loader2 size={15} className="spin" /> : <Play size={15} strokeWidth={2} />}
            Run
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => judge.mutate("submit")}
            disabled={busy || !text.trim()}
            title="Judge on every hidden test"
          >
            {busy && judge.variables === "submit" ? <Loader2 size={15} className="spin" /> : <Send size={15} strokeWidth={2} />}
            Submit
          </button>
          {busy && (
            <span className="study-job" role="status">
              {judge.variables === "submit" ? "Running the hidden tests" : "Running the samples"}
            </span>
          )}
        </div>
      </section>

      {error && <p className="error-text">{error}</p>}
      {result && <Results result={result} kind={problem.kind} />}

      <section className="practice-solution">
        {problem.reference != null ? (
          <>
            <div className="practice-solution-head">
              <h3>Official solution</h3>
              {problem.solved && (
                <span className="practice-solved">
                  <BadgeCheck size={14} strokeWidth={2} /> Solved
                </span>
              )}
              <span className="study-muted study-small">{solutionLang}</span>
            </div>
            <Pre text={problem.reference} className="practice-code" />
          </>
        ) : (
          <button
            type="button"
            className="btn"
            disabled={reveal.isPending}
            onClick={() => {
              if (window.confirm("Reveal the official solution? You can still submit.")) reveal.mutate();
            }}
          >
            {reveal.isPending ? <Loader2 size={15} className="spin" /> : <Eye size={15} strokeWidth={1.75} />}
            Show solution
          </button>
        )}
      </section>

      <details className="practice-history">
        <summary>
          <History size={15} strokeWidth={1.75} /> Submissions
          {submissions.data && submissions.data.length > 0 && (
            <span className="practice-count">{submissions.data.length}</span>
          )}
        </summary>
        {submissions.isLoading && (
          <p className="study-muted study-small">
            <Loader2 size={13} className="spin" /> Loading
          </p>
        )}
        {submissions.isError && <p className="error-text">Could not load your submissions.</p>}
        {submissions.data?.length === 0 && (
          <p className="study-muted study-small">Nothing yet. Run or submit to see your attempts here.</p>
        )}
        {submissions.data && submissions.data.length > 0 && (
          <ul className="practice-subs">
            {submissions.data.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  className="practice-sub"
                  onClick={() => loadSubmission(s)}
                  title="Load this code into the editor"
                >
                  <span className={`practice-chip mode-${s.mode}`}>{s.mode === "run" ? "Run" : "Submit"}</span>
                  <span className={`practice-tone ${verdictTone(s.verdict)}`}>{verdictLabel(s.verdict)}</span>
                  <span className="mono practice-sub-score">
                    {s.total > 0 ? `${s.passed}/${s.total}` : ""}
                  </span>
                  {s.language && <span className="study-muted study-small">{LANG_LABEL[s.language]}</span>}
                  <span className="study-muted study-small practice-sub-time">{timeAgo(s.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </details>
    </div>
  );
}

export function ProblemPage() {
  const { problemId } = useParams({ from: "/practice/$problemId" });
  const qc = useQueryClient();
  const navigate = useNavigate();
  const problem = useQuery({
    queryKey: ["practice-problem", problemId],
    queryFn: () => api.get<ProblemOut>(`/api/practice/problems/${problemId}`),
    refetchInterval: (q) => (q.state.data && isActive(q.state.data.status) ? 3000 : false),
  });
  const p = problem.data;

  const remove = useMutation({
    mutationFn: () => api.delete(`/api/practice/problems/${problemId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["practice-problems"] });
      navigate({ to: "/practice" });
    },
  });

  // When generation finishes elsewhere, refresh the list too.
  const status = p?.status;
  useEffect(() => {
    if (status === "ready" || status === "failed") qc.invalidateQueries({ queryKey: ["practice-problems"] });
  }, [status, qc]);

  const chips = useMemo(() => {
    if (!p) return [];
    return [
      KIND_LABEL[p.kind] ?? p.kind,
      ...(p.language ? [LANG_LABEL[p.language] ?? p.language] : []),
      p.difficulty,
    ];
  }, [p]);

  return (
    <div className="practice-page practice-problem">
      <nav className="crumb">
        <Link to="/practice">
          <ChevronLeft size={15} strokeWidth={1.5} /> Practice
        </Link>
      </nav>

      {problem.isLoading && (
        <div className="study-skeleton" aria-hidden>
          {[0, 1, 2].map((i) => (
            <div key={i} className="study-skel-row" />
          ))}
        </div>
      )}
      {problem.isError && (
        <div className="practice-empty">
          <p className="error-text">{(problem.error as Error).message || "Could not load this problem."}</p>
          <button type="button" className="btn" onClick={() => problem.refetch()}>
            Retry
          </button>
        </div>
      )}

      {p && (
        <>
          <header className="practice-problem-head">
            <div className="practice-problem-title">
              <h1>{isActive(p.status) ? "Writing a problem…" : p.title || "Untitled problem"}</h1>
              {p.solved && (
                <span className="practice-solved big">
                  <BadgeCheck size={15} strokeWidth={2} /> Solved
                </span>
              )}
            </div>
            <div className="practice-chips">
              {chips.map((c, i) => (
                <span key={c} className={`practice-chip${i === 0 ? " kind" : ""}${i === chips.length - 1 ? ` diff-${p.difficulty}` : ""}`}>
                  {c}
                </span>
              ))}
              {p.topic && <span className="practice-row-topic">{p.topic}</span>}
            </div>
          </header>

          {isActive(p.status) && (
            <div className="practice-pending">
              <ProgressNote problem={p} />
              <p className="study-muted study-small">
                The AI writes the statement and a reference solution, then the server runs the reference to get
                the expected outputs. This takes 1–3 minutes; you can leave this page.
              </p>
            </div>
          )}

          {p.status === "failed" && (
            <div className="practice-pending failed">
              <p className="error-text">{p.error || "This problem could not be written."}</p>
              <button type="button" className="btn" onClick={() => remove.mutate()} disabled={remove.isPending}>
                <Trash2 size={14} strokeWidth={1.75} /> Delete
              </button>
            </div>
          )}

          {p.status === "ready" && (
            <div className="practice-split">
              <article className="practice-statement">
                <Markdown className="practice-md practice-md-main">{p.statement}</Markdown>
                {p.kind === "code" ? <CodeStatement problem={p} /> : <TheoryStatement problem={p} />}
              </article>
              <Workspace key={p.id} problem={p} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
