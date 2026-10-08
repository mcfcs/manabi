import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearch } from "@tanstack/react-router";
import { Check, ChevronRight, Code2, Loader2, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  api,
  type CourseOut,
  type JobOut,
  type ModuleOut,
  type PlanOut,
  type PracticeKind,
  type PracticeLanguage,
  type ProblemSummary,
} from "../../lib/api";
import { isActive, KIND_LABEL, LANG_LABEL, LANGS, timeAgo } from "./shared";
import "./practice.css";

type Difficulty = "easy" | "medium" | "hard";
type Source = "materials" | "original";

/** Progress of one problem's generation job, polled every 3 s while active. */
export function usePracticeJob(jobId: number | null, active: boolean) {
  return useQuery({
    queryKey: ["practice-job", jobId],
    enabled: jobId != null && active,
    queryFn: () => api.get<JobOut>(`/api/jobs/${jobId}`),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "succeeded" || s === "failed" || s === "cancelled" ? false : 3000;
    },
  });
}

export function ProgressNote({ problem }: { problem: ProblemSummary }) {
  const active = isActive(problem.status);
  const job = usePracticeJob(problem.job_id, active);
  if (!active) return null;
  const live = job.data?.status === "queued" || job.data?.status === "running";
  const note =
    (live && job.data?.progress_note) ||
    (job.data?.status === "queued"
      ? "Waiting for the AI node"
      : problem.status === "validating"
        ? "Checking the reference solution"
        : "Writing the problem");
  return (
    <span className="practice-progress" role="status">
      <Loader2 size={13} className="spin" /> {note}
      {live && job.data?.progress_pct != null && <span className="mono"> {job.data.progress_pct}%</span>}
    </span>
  );
}

// ── New problem panel ──────────────────────────────────────────────────

function NewProblem({
  courses,
  initial,
  onCreated,
}: {
  courses: CourseOut[];
  initial: { course?: number; plan?: number; module?: number };
  onCreated: (p: ProblemSummary) => void;
}) {
  const [kind, setKind] = useState<PracticeKind>("code");
  const [language, setLanguage] = useState<PracticeLanguage>("cpp");
  const [courseId, setCourseId] = useState<number | null>(initial.course ?? null);
  const [planId, setPlanId] = useState<number | null>(initial.plan ?? null);
  const [moduleId, setModuleId] = useState<number | null>(initial.module ?? null);
  const [topic, setTopic] = useState("");
  const [difficulty, setDifficulty] = useState<Difficulty>("medium");
  const [source, setSource] = useState<Source>(initial.module ? "materials" : "original");

  // Arriving from a study plan's "Coding lab" link while already on the page.
  useEffect(() => {
    if (initial.course == null) return;
    setCourseId(initial.course);
    setPlanId(initial.plan ?? null);
    setModuleId(initial.module ?? null);
    if (initial.module) setSource("materials");
  }, [initial.course, initial.plan, initial.module]);

  const modules = useQuery({
    queryKey: ["modules", String(courseId)],
    queryFn: () => api.get<ModuleOut[]>(`/api/courses/${courseId}/modules`),
    enabled: courseId != null,
  });
  const plans = useQuery({
    queryKey: ["plans", String(courseId)],
    queryFn: () => api.get<PlanOut[]>(`/api/courses/${courseId}/plans`),
    enabled: courseId != null,
  });
  const plan = plans.data?.find((p) => p.id === planId) ?? null;
  const moduleOptions = useMemo(() => {
    const all = modules.data ?? [];
    return plan ? all.filter((m) => plan.module_ids.includes(m.id)) : all;
  }, [modules.data, plan]);

  const hasPlans = courseId != null && (plans.data?.length ?? 0) > 0;
  const effectiveSource: Source = moduleId != null ? source : "original";
  const theory = kind !== "code";

  const create = useMutation({
    mutationFn: () =>
      api.post<ProblemSummary>("/api/practice/problems", {
        kind,
        ...(kind === "code" ? { language } : {}),
        course_id: courseId,
        module_id: moduleId,
        plan_id: planId,
        topic: topic.trim() || null,
        difficulty,
        source: effectiveSource,
      }),
    onSuccess: (p) => {
      setTopic("");
      onCreated(p);
    },
    onError: () => undefined, // shown inline below
  });

  return (
    <section className="practice-new" aria-labelledby="practice-new-h">
      <h2 id="practice-new-h">
        <Sparkles size={17} strokeWidth={1.75} /> New problem
      </h2>

      <div className="practice-field span-2">
        <span className="field-label">Kind</span>
        <div className="seg practice-seg" role="radiogroup" aria-label="Kind">
          {(Object.keys(KIND_LABEL) as PracticeKind[]).map((k) => (
            <button
              key={k}
              type="button"
              role="radio"
              aria-checked={kind === k}
              className={`seg-btn${kind === k ? " active" : ""}`}
              onClick={() => setKind(k)}
            >
              {KIND_LABEL[k]}
            </button>
          ))}
        </div>
        <span className="gen-hint">
          {kind === "code"
            ? "A program judged on stdin / stdout."
            : kind === "grammar"
              ? "Write a context-free grammar for a language."
              : kind === "regex"
                ? "Write a regular expression for a language."
                : "Draw a DFA as a transition list."}
        </span>
      </div>

      {kind === "code" && (
        <label className="practice-field">
          <span className="field-label">Language</span>
          <select
            className="input"
            value={language}
            onChange={(e) => setLanguage(e.target.value as PracticeLanguage)}
          >
            {LANGS.map((l) => (
              <option key={l} value={l}>
                {LANG_LABEL[l]}
              </option>
            ))}
          </select>
        </label>
      )}

      <div className={`practice-field${theory ? " span-2" : ""}`}>
        <span className="field-label">Difficulty</span>
        <div className="seg practice-seg" role="radiogroup" aria-label="Difficulty">
          {(["easy", "medium", "hard"] as Difficulty[]).map((d) => (
            <button
              key={d}
              type="button"
              role="radio"
              aria-checked={difficulty === d}
              className={`seg-btn${difficulty === d ? " active" : ""}`}
              onClick={() => setDifficulty(d)}
            >
              {d[0].toUpperCase() + d.slice(1)}
            </button>
          ))}
        </div>
      </div>

      <label className="practice-field span-2">
        <span className="field-label">Course</span>
        <select
          className="input"
          value={courseId ?? ""}
          onChange={(e) => {
            const v = e.target.value ? Number(e.target.value) : null;
            setCourseId(v);
            setModuleId(null);
            setPlanId(null);
          }}
        >
          <option value="">Personal — no course</option>
          {courses.map((c) => (
            <option key={c.id} value={c.id}>
              {c.code} · {c.name}
            </option>
          ))}
        </select>
      </label>

      {hasPlans && (
        <label className="practice-field">
          <span className="field-label">Study plan</span>
          <select
            className="input"
            value={planId ?? ""}
            onChange={(e) => {
              const v = e.target.value ? Number(e.target.value) : null;
              setPlanId(v);
              const p = plans.data?.find((x) => x.id === v);
              if (p && moduleId != null && !p.module_ids.includes(moduleId)) setModuleId(null);
            }}
          >
            <option value="">No study plan</option>
            {plans.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      )}

      {courseId != null && (
        <label className={`practice-field${hasPlans ? "" : " span-2"}`}>
          <span className="field-label">Module</span>
          <select
            className="input"
            value={moduleId ?? ""}
            disabled={modules.isLoading}
            onChange={(e) => {
              const v = e.target.value ? Number(e.target.value) : null;
              setModuleId(v);
              if (v != null) setSource("materials");
            }}
          >
            <option value="">{modules.isLoading ? "Loading modules…" : "Any — no module"}</option>
            {moduleOptions.map((m) => (
              <option key={m.id} value={m.id}>
                {m.title}
              </option>
            ))}
          </select>
          {modules.isError && <span className="error-text">Could not load the modules.</span>}
        </label>
      )}

      <label className="practice-field span-2">
        <span className="field-label">Topic (optional)</span>
        <input
          className="input"
          value={topic}
          maxLength={1000}
          onChange={(e) => setTopic(e.target.value)}
          placeholder={
            theory ? "e.g. strings over {a,b} with even a's" : "e.g. a stack with push/pop (HW1)"
          }
        />
      </label>

      <div className="practice-field span-2">
        <span className="field-label">Source</span>
        <div className="seg practice-seg" role="radiogroup" aria-label="Source">
          <button
            type="button"
            role="radio"
            aria-checked={effectiveSource === "materials"}
            className={`seg-btn${effectiveSource === "materials" ? " active" : ""}`}
            disabled={moduleId == null}
            onClick={() => setSource("materials")}
            title={moduleId == null ? "Pick a module first" : "Write it from this module's material"}
          >
            From my materials
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={effectiveSource === "original"}
            className={`seg-btn${effectiveSource === "original" ? " active" : ""}`}
            onClick={() => setSource("original")}
          >
            Original
          </button>
        </div>
        <span className="gen-hint">
          {moduleId == null
            ? "Pick a module to write the problem from your materials."
            : effectiveSource === "materials"
              ? "Built from this module's slides and readings."
              : "A fresh problem on the topic, not tied to your materials."}
        </span>
      </div>

      <div className="practice-new-foot">
      <button
        type="button"
        className="btn btn-primary practice-generate"
        onClick={() => create.mutate()}
        disabled={create.isPending}
      >
        {create.isPending ? <Loader2 size={15} className="spin" /> : <Sparkles size={15} strokeWidth={1.75} />}
        Generate
      </button>
      {create.isError && <p className="error-text">{(create.error as Error).message}</p>}
      <p className="gen-hint practice-new-note">
        Writing and checking a problem takes 1–3 minutes. The expected outputs come from running a hidden
        reference solution.
      </p>
      </div>
    </section>
  );
}

// ── Problem list ───────────────────────────────────────────────────────

function ProblemRow({
  p,
  course,
  onDelete,
}: {
  p: ProblemSummary;
  course: CourseOut | undefined;
  onDelete: (p: ProblemSummary) => void;
}) {
  const active = isActive(p.status);
  const failed = p.status === "failed";
  return (
    <li className={`practice-row${p.solved ? " solved" : ""}${failed ? " failed" : ""}`}>
      <Link
        to="/practice/$problemId"
        params={{ problemId: String(p.id) }}
        className="practice-row-link"
      >
        <span className="practice-row-mark" aria-hidden>
          {p.solved ? (
            <Check size={14} strokeWidth={2.5} />
          ) : active ? (
            <Loader2 size={14} className="spin" />
          ) : (
            <Code2 size={14} strokeWidth={1.75} />
          )}
        </span>
        <span className="practice-row-main">
          <span className="practice-row-title">
            {active ? "Writing…" : failed && !p.title ? "Could not write this problem" : p.title || "Untitled"}
          </span>
          <span className="practice-chips">
            <span className="practice-chip kind">{KIND_LABEL[p.kind] ?? p.kind}</span>
            {p.language && <span className="practice-chip">{LANG_LABEL[p.language] ?? p.language}</span>}
            <span className={`practice-chip diff-${p.difficulty}`}>{p.difficulty}</span>
            {course && (
              <span className="practice-chip course">
                <span className="practice-dot" style={{ background: course.accent_color ?? "var(--accent-blue)" }} />
                {course.code}
              </span>
            )}
            {p.topic && !active && <span className="practice-row-topic">{p.topic}</span>}
          </span>
          {active && <ProgressNote problem={p} />}
          {failed && <span className="error-text practice-row-error">{p.error || "Generation failed."}</span>}
        </span>
        <span className="practice-row-side">
          {p.solved ? (
            <span className="practice-solved">Solved</span>
          ) : p.best_total ? (
            <span className="practice-best mono">
              {p.best_passed ?? 0}/{p.best_total}
            </span>
          ) : !active && !failed ? (
            <span className="study-muted study-small">{timeAgo(p.created_at)}</span>
          ) : null}
          {!failed && <ChevronRight size={16} className="practice-row-chev" />}
        </span>
      </Link>
      {failed ? (
        <button type="button" className="btn practice-row-del" onClick={() => onDelete(p)}>
          <Trash2 size={14} strokeWidth={1.75} /> Delete
        </button>
      ) : (
        <button
          type="button"
          className="icon-btn danger practice-row-x"
          onClick={() => onDelete(p)}
          aria-label={`Delete ${p.title || "problem"}`}
          title="Delete"
        >
          <Trash2 size={15} strokeWidth={1.5} />
        </button>
      )}
    </li>
  );
}

// ── Page ───────────────────────────────────────────────────────────────

export function PracticePage() {
  const search = useSearch({ from: "/practice" });
  const qc = useQueryClient();
  const courses = useQuery({
    queryKey: ["courses"],
    queryFn: () => api.get<CourseOut[]>("/api/courses"),
    staleTime: 30_000,
  });
  const list = useQuery({
    queryKey: ["practice-problems"],
    queryFn: () => api.get<ProblemSummary[]>("/api/practice/problems"),
    refetchInterval: (q) => (q.state.data?.some((p) => isActive(p.status)) ? 3000 : false),
  });
  const [courseFilter, setCourseFilter] = useState<string>(
    search.course != null ? String(search.course) : "all",
  );
  useEffect(() => {
    if (search.course != null) setCourseFilter(String(search.course));
  }, [search.course]);
  const [solvedFilter, setSolvedFilter] = useState<"all" | "unsolved" | "solved">("all");

  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/api/practice/problems/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["practice-problems"] }),
  });

  const activeCourses = useMemo(() => (courses.data ?? []).filter((c) => !c.archived), [courses.data]);
  const courseById = useMemo(
    () => new Map((courses.data ?? []).map((c) => [c.id, c])),
    [courses.data],
  );

  const problems = useMemo(() => {
    return (list.data ?? [])
      .filter((p) =>
        courseFilter === "all"
          ? true
          : courseFilter === "none"
            ? p.course_id == null
            : String(p.course_id) === courseFilter,
      )
      .filter((p) => (solvedFilter === "all" ? true : solvedFilter === "solved" ? p.solved : !p.solved))
      .sort((a, b) => b.id - a.id);
  }, [list.data, courseFilter, solvedFilter]);

  const total = list.data?.length ?? 0;
  const solvedCount = list.data?.filter((p) => p.solved).length ?? 0;

  return (
    <div className="practice-page">
      <header className="practice-head">
        <h1>Practice</h1>
        <p className="practice-head-sub">
          Judged problems: programs in C, C++ or Python checked on hidden tests, and grammars, regular
          expressions and DFAs checked string by string.
        </p>
        {total > 0 && (
          <p className="practice-head-count">
            {solvedCount} of {total} solved
          </p>
        )}
      </header>

      <div className="practice-layout">
        <NewProblem
          courses={activeCourses}
          initial={search}
          onCreated={(p) => {
            qc.setQueryData<ProblemSummary[]>(["practice-problems"], (old) => [
              p,
              ...(old ?? []).filter((x) => x.id !== p.id),
            ]);
            qc.invalidateQueries({ queryKey: ["practice-problems"] });
            if (courseFilter !== "all" && String(p.course_id ?? "none") !== courseFilter) setCourseFilter("all");
            if (solvedFilter === "solved") setSolvedFilter("all");
          }}
        />

        <section className="practice-list-wrap" aria-labelledby="practice-list-h">
          <div className="practice-list-bar">
            <h2 id="practice-list-h">Problems</h2>
            <div className="practice-filters">
              <select
                className="input practice-filter-course"
                value={courseFilter}
                onChange={(e) => setCourseFilter(e.target.value)}
                aria-label="Filter by course"
              >
                <option value="all">All courses</option>
                <option value="none">Personal</option>
                {(courses.data ?? []).map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.code}
                  </option>
                ))}
              </select>
              <div className="seg practice-seg practice-seg-compact" role="radiogroup" aria-label="Solved filter">
                {(["all", "unsolved", "solved"] as const).map((k) => (
                  <button
                    key={k}
                    type="button"
                    role="radio"
                    aria-checked={solvedFilter === k}
                    className={`seg-btn${solvedFilter === k ? " active" : ""}`}
                    onClick={() => setSolvedFilter(k)}
                  >
                    {k[0].toUpperCase() + k.slice(1)}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {list.isLoading && (
            <div className="study-skeleton" aria-hidden>
              {[0, 1, 2].map((i) => (
                <div key={i} className="study-skel-row" />
              ))}
            </div>
          )}
          {list.isError && (
            <p className="error-text">
              Could not load your problems.{" "}
              <button type="button" className="link-btn" onClick={() => list.refetch()}>
                Retry
              </button>
            </p>
          )}
          {list.data && total === 0 && (
            <div className="practice-empty">
              <Code2 size={22} strokeWidth={1.5} />
              <p>No problems yet — generate one above.</p>
            </div>
          )}
          {list.data && total > 0 && problems.length === 0 && (
            <div className="practice-empty">
              <p>No problems match these filters.</p>
              <button
                type="button"
                className="link-btn"
                onClick={() => {
                  setCourseFilter("all");
                  setSolvedFilter("all");
                }}
              >
                Show all
              </button>
            </div>
          )}
          {problems.length > 0 && (
            <ul className="practice-list">
              {problems.map((p) => (
                <ProblemRow
                  key={p.id}
                  p={p}
                  course={p.course_id != null ? courseById.get(p.course_id) : undefined}
                  onDelete={(x) => {
                    if (x.status !== "failed" && !window.confirm(`Delete “${x.title || "this problem"}” and its submissions?`))
                      return;
                    remove.mutate(x.id);
                  }}
                />
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
