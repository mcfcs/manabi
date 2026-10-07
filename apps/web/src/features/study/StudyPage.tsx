import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import {
  BookOpen,
  Check,
  ChevronDown,
  ChevronLeft,
  GraduationCap,
  Headphones,
  ListChecks,
  Loader2,
  PenLine,
  Play,
  Plus,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Markdown } from "../../components/Markdown";
import {
  api,
  type CourseOut,
  type JobRef,
  type QuizListItem,
  type QuizOut,
  type StudyModuleOut,
  type StudyOut,
  type SummaryOut,
} from "../../lib/api";
import { ExamPlayer } from "../ai/ExamPlayer";
import { useJob } from "../ai/common";
import "./study.css";

const PASS = 70;

type Preset = "output" | "balanced" | "theory";

const PRESETS: Record<Preset, { label: string; hint: string; types: string[]; mix: Record<string, number> }> = {
  output: {
    label: "Output",
    hint: "Mostly what-does-this-print, plus code-reading choices",
    types: ["output", "mcq", "tf", "identification"],
    mix: { output: 5, mcq: 4, tf: 1, identification: 1 },
  },
  balanced: {
    label: "Balanced",
    hint: "Even mix of code tracing and concepts",
    types: ["output", "mcq", "tf", "identification"],
    mix: { output: 3, mcq: 4, tf: 2, identification: 2 },
  },
  theory: {
    label: "Concepts",
    hint: "Definitions, comparisons and rules; for readings",
    types: ["mcq", "tf", "identification", "enumeration"],
    mix: { mcq: 5, tf: 3, identification: 3, enumeration: 1 },
  },
};

// Jobs started from this page, remembered per course so progress survives a
// reload (per-device convenience only; the server is the source of truth).
function useStudyJobs(courseId: string) {
  const key = `manabi-study-jobs-${courseId}`;
  const [jobs, setJobs] = useState<Record<string, number>>(() => {
    try {
      return JSON.parse(localStorage.getItem(key) ?? "{}");
    } catch {
      return {};
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(jobs));
    } catch {
      /* ignore */
    }
  }, [key, jobs]);
  return {
    jobs,
    add: (k: string, id: number) => setJobs((j) => ({ ...j, [k]: id })),
    done: (k: string) =>
      setJobs((j) => {
        const n = { ...j };
        delete n[k];
        return n;
      }),
  };
}

function JobLine({ jobId, onDone }: { jobId: number; onDone: (ok: boolean) => void }) {
  const job = useJob(jobId);
  const s = job.data?.status;
  useEffect(() => {
    if (s === "succeeded") onDone(true);
    if (s === "failed" || s === "cancelled") onDone(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s]);
  if (s === "failed") return <p className="error-text study-job">Generation failed: {job.data?.error}</p>;
  return (
    <p className="study-job" role="status">
      <Loader2 size={13} className="spin" />{" "}
      {job.data?.progress_note || (s === "queued" ? "Waiting for the AI node" : "Starting")}
    </p>
  );
}

function scoreLabel(q: QuizListItem | null | undefined) {
  if (!q) return null;
  if (q.best_score == null) return "Not taken";
  return `Best ${Math.round(q.best_score)}%`;
}

function passed(q: QuizListItem | null | undefined) {
  return q?.best_score != null && q.best_score >= PASS;
}

// ── One section of a module's study notes ──────────────────────────────

function SectionRow({
  module,
  index,
  title,
  bestScore,
  quizId,
  hasSources,
  summary,
  jobId,
  onCheck,
  onPlay,
  onJobDone,
  open,
  onToggle,
  onNext,
}: {
  module: StudyModuleOut;
  index: number;
  title: string;
  bestScore: number | null;
  quizId: number | null;
  hasSources: boolean;
  summary: SummaryOut | undefined;
  jobId: number | undefined;
  onCheck: () => void;
  onPlay: (id: number) => void;
  onJobDone: (ok: boolean) => void;
  open: boolean;
  onToggle: () => void;
  onNext: (() => void) | null;
}) {
  const section = summary?.sections[index];
  const done = bestScore != null && bestScore >= PASS;
  return (
    <li className={`study-sec${open ? " open" : ""}${done ? " done" : ""}`}>
      <div className="study-sec-row">
        <button type="button" className="study-sec-title" onClick={onToggle} aria-expanded={open}>
          <span className="study-sec-mark" aria-hidden>
            {done ? <Check size={13} strokeWidth={2.5} /> : index + 1}
          </span>
          <span className="study-sec-name">{title}</span>
          <ChevronDown size={15} className="study-chev" />
        </button>
        {quizId != null && bestScore != null && (
          <span className={`study-score${done ? " ok" : " low"}`}>{Math.round(bestScore)}%</span>
        )}
      </div>
      {open && (
        <div className="study-sec-body">
          {!section ? (
            <p className="study-muted">
              <Loader2 size={13} className="spin" /> Loading the notes
            </p>
          ) : (
            <div className="study-reading">
              {section.blocks.map((b, i) => (
                <Markdown key={i} className="study-block">
                  {b.text}
                </Markdown>
              ))}
            </div>
          )}
          <div className="study-sec-actions">
            {jobId != null ? (
              <JobLine jobId={jobId} onDone={onJobDone} />
            ) : quizId != null ? (
              <>
                <button type="button" className="btn btn-primary" onClick={() => onPlay(quizId)}>
                  <Play size={14} strokeWidth={2} /> {bestScore == null ? "Check this section" : "Retake check"}
                </button>
                <button type="button" className="btn" onClick={onCheck} title="Write a fresh set of questions">
                  New questions
                </button>
              </>
            ) : (
              <button
                type="button"
                className="btn btn-primary"
                onClick={onCheck}
                disabled={!hasSources}
                title={hasSources ? "Four quick questions on this section" : "This section cites no material"}
              >
                <ListChecks size={15} strokeWidth={1.75} /> Check this section
              </button>
            )}
            {onNext && (
              <button type="button" className="link-btn" onClick={onNext}>
                Next section
              </button>
            )}
          </div>
          {module.lecture_id != null && index === 0 && (
            <p className="study-muted study-sec-note">
              Prefer listening? Steven's lesson covers this module start to finish.
            </p>
          )}
        </div>
      )}
    </li>
  );
}

// ── One module (a step on the path) ────────────────────────────────────

function ModuleStep({
  n,
  courseId,
  module,
  open,
  onToggle,
  jobs,
  startJob,
  finishJob,
  onPlay,
  preset,
}: {
  n: number;
  courseId: string;
  module: StudyModuleOut;
  open: boolean;
  onToggle: () => void;
  jobs: Record<string, number>;
  startJob: (key: string, run: () => Promise<JobRef>) => void;
  finishJob: (key: string, ok: boolean) => void;
  onPlay: (quizId: number) => void;
  preset: Preset;
}) {
  const [openSec, setOpenSec] = useState<number | null>(null);
  const summary = useQuery({
    queryKey: ["summary", String(module.id)],
    queryFn: () => api.get<SummaryOut | null>(`/api/modules/${module.id}/summary`),
    enabled: open && module.summary_id != null,
    staleTime: 60_000,
  });

  const cp = module.checkpoint;
  const isDone = passed(cp);
  const checked = module.sections.filter((s) => s.best_score != null && s.best_score >= PASS).length;
  const p = PRESETS[module.language ? preset : "theory"];

  const kSummary = `summary:${module.id}`;
  const kCheckpoint = `checkpoint:${module.id}`;
  const kLecture = `lecture:${module.id}`;

  return (
    <li className={`study-step${open ? " open" : ""}${isDone ? " done" : ""}`}>
      <button type="button" className="study-step-head" onClick={onToggle} aria-expanded={open}>
        <span className="study-step-num" aria-hidden>
          {isDone ? <Check size={16} strokeWidth={2.5} /> : n}
        </span>
        <span className="study-step-text">
          <span className="study-step-title">{module.title}</span>
          <span className="study-step-meta">
            {module.sections.length > 0
              ? `${checked} of ${module.sections.length} sections checked`
              : module.has_material
                ? "No study notes yet"
                : "No materials yet"}
            {cp && `, topic test ${scoreLabel(cp)?.toLowerCase()}`}
          </span>
        </span>
        <ChevronDown size={18} className="study-chev" />
      </button>

      {open && (
        <div className="study-step-body">
          {!module.has_material ? (
            <p className="study-muted">
              Upload this module's slides or readings first, then come back.{" "}
              <Link
                to="/courses/$courseId/modules/$moduleId"
                params={{ courseId, moduleId: String(module.id) }}
                search={{ tab: "materials" }}
              >
                Open materials
              </Link>
            </p>
          ) : (
            <>
              <section className="study-part">
                <h4>
                  <BookOpen size={15} strokeWidth={1.75} /> Learn
                </h4>
                {module.sections.length > 0 ? (
                  <ol className="study-secs">
                    {module.sections.map((s) => (
                      <SectionRow
                        key={s.index}
                        module={module}
                        index={s.index}
                        title={s.title}
                        bestScore={s.best_score}
                        quizId={s.quiz_id}
                        hasSources={s.has_sources}
                        summary={summary.data ?? undefined}
                        jobId={jobs[`section:${module.id}:${s.index}`]}
                        open={openSec === s.index}
                        onToggle={() => setOpenSec((v) => (v === s.index ? null : s.index))}
                        onNext={
                          s.index + 1 < module.sections.length ? () => setOpenSec(s.index + 1) : null
                        }
                        onPlay={onPlay}
                        onJobDone={(ok) => finishJob(`section:${module.id}:${s.index}`, ok)}
                        onCheck={() =>
                          startJob(`section:${module.id}:${s.index}`, () =>
                            api.post<JobRef>("/api/quizzes", {
                              module_ids: [module.id],
                              types: ["mcq", "tf", "identification", ...(module.language ? ["output"] : [])],
                              type_mix: module.language
                                ? { mcq: 3, output: 2, tf: 1, identification: 1 }
                                : { mcq: 3, tf: 1, identification: 1 },
                              count: 4,
                              mode: "sources",
                              section: s.index,
                            }),
                          )
                        }
                      />
                    ))}
                  </ol>
                ) : jobs[kSummary] != null ? (
                  <JobLine jobId={jobs[kSummary]} onDone={(ok) => finishJob(kSummary, ok)} />
                ) : (
                  <div className="study-empty-row">
                    <p className="study-muted">Steven writes section-by-section notes from your materials first.</p>
                    <button
                      type="button"
                      className="btn"
                      onClick={() =>
                        startJob(kSummary, () => api.post<JobRef>(`/api/modules/${module.id}/summary/generate`))
                      }
                    >
                      <PenLine size={15} strokeWidth={1.75} /> Write study notes
                    </button>
                  </div>
                )}

                <div className="study-steven">
                  <img src="/steven.jpg" alt="" className="study-steven-avatar" />
                  <div className="study-steven-text">
                    <strong>Steven's lesson</strong>
                    <span className="study-muted">
                      {module.lecture_id != null
                        ? `${module.lecture_segments} spoken parts with checkpoints`
                        : "A narrated walk through the module"}
                    </span>
                  </div>
                  {jobs[kLecture] != null ? (
                    <JobLine jobId={jobs[kLecture]} onDone={(ok) => finishJob(kLecture, ok)} />
                  ) : module.lecture_id != null ? (
                    <Link
                      className="btn"
                      to="/courses/$courseId/modules/$moduleId"
                      params={{ courseId, moduleId: String(module.id) }}
                      search={{ tab: "teacher" }}
                    >
                      <Headphones size={15} strokeWidth={1.75} /> Listen
                    </Link>
                  ) : (
                    <button
                      type="button"
                      className="btn"
                      onClick={() =>
                        startJob(kLecture, () =>
                          api.post<JobRef>(`/api/modules/${module.id}/lecture/generate`, { mode: "standard" }),
                        )
                      }
                    >
                      Prepare lesson
                    </button>
                  )}
                </div>
              </section>

              <section className="study-part">
                <h4>
                  <ListChecks size={15} strokeWidth={1.75} /> Topic test
                </h4>
                <p className="study-muted study-part-hint">
                  12 questions across the whole module, {p.hint.toLowerCase()}. Pass mark {PASS}%.
                </p>
                {jobs[kCheckpoint] != null ? (
                  <JobLine jobId={jobs[kCheckpoint]} onDone={(ok) => finishJob(kCheckpoint, ok)} />
                ) : (
                  <div className="study-part-actions">
                    {cp && (
                      <button type="button" className="btn btn-primary" onClick={() => onPlay(cp.artifact_id)}>
                        <Play size={14} strokeWidth={2} /> {cp.best_score == null ? "Take the test" : "Retake"}
                      </button>
                    )}
                    {cp?.best_score != null && (
                      <span className={`study-score${isDone ? " ok" : " low"}`}>{scoreLabel(cp)}</span>
                    )}
                    <button
                      type="button"
                      className={cp ? "btn" : "btn btn-primary"}
                      onClick={() =>
                        startJob(kCheckpoint, () =>
                          api.post<JobRef>("/api/quizzes", {
                            module_ids: [module.id],
                            types: p.types,
                            type_mix: p.mix,
                            count: 12,
                            mode: "exercise",
                            role: "checkpoint",
                          }),
                        )
                      }
                    >
                      {cp ? "New version" : (
                        <>
                          <Plus size={15} strokeWidth={2} /> Build topic test
                        </>
                      )}
                    </button>
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      )}
    </li>
  );
}

// ── The final exam panel ───────────────────────────────────────────────

function FinalPanel({
  data,
  jobs,
  startJob,
  finishJob,
  onPlay,
  preset,
  setPreset,
}: {
  data: StudyOut;
  jobs: Record<string, number>;
  startJob: (key: string, run: () => Promise<JobRef>) => void;
  finishJob: (key: string, ok: boolean) => void;
  onPlay: (id: number) => void;
  preset: Preset;
  setPreset: (p: Preset) => void;
}) {
  const [count, setCount] = useState(40);
  const withMaterial = data.modules.filter((m) => m.has_material);
  const [picked, setPicked] = useState<number[] | null>(null);
  const scope = picked ?? withMaterial.map((m) => m.id);
  const latest = data.finals[0];
  const p = PRESETS[preset];
  const wide = typeof window !== "undefined" && window.matchMedia("(min-width: 1024px)").matches;
  const minutes = Math.round(count * 1.5);

  return (
    <aside className="study-final">
      <div className="study-final-head">
        <GraduationCap size={20} strokeWidth={1.5} />
        <h2>Final mock exam</h2>
      </div>
      <p className="study-muted">
        Every module in one long, timed test. Answers are revealed only after you submit, with a breakdown
        by module and topic.
      </p>

      {latest && (
        <div className="study-final-latest">
          <div>
            <strong>{latest.question_count} questions</strong>
            <span className="study-muted">
              {latest.best_score != null ? `Best ${Math.round(latest.best_score)}%` : "Not taken yet"}
              {latest.attempt_count > 0 && `, ${latest.attempt_count} attempt${latest.attempt_count === 1 ? "" : "s"}`}
            </span>
          </div>
          <button type="button" className="btn btn-primary" onClick={() => onPlay(latest.artifact_id)}>
            <Play size={14} strokeWidth={2} /> {latest.attempt_count ? "Retake" : "Start"}
          </button>
        </div>
      )}

      {jobs.final != null ? (
        <JobLine jobId={jobs.final} onDone={(ok) => finishJob("final", ok)} />
      ) : (
        <details className="study-final-build" open={!latest && wide}>
          <summary>{latest ? "Build a new version" : "Build the exam"}</summary>
          <div className="study-field">
            <span className="field-label">Style</span>
            <div className="seg study-seg">
              {(Object.keys(PRESETS) as Preset[]).map((k) => (
                <button
                  key={k}
                  type="button"
                  className={`seg-btn${preset === k ? " active" : ""}`}
                  onClick={() => setPreset(k)}
                >
                  {PRESETS[k].label}
                </button>
              ))}
            </div>
            <span className="study-muted study-small">{p.hint}</span>
          </div>
          <div className="study-field">
            <span className="field-label">Length</span>
            <div className="seg study-seg">
              {[20, 40, 60].map((n) => (
                <button
                  key={n}
                  type="button"
                  className={`seg-btn${count === n ? " active" : ""}`}
                  onClick={() => setCount(n)}
                >
                  {n}
                </button>
              ))}
            </div>
            <span className="study-muted study-small">About {minutes} minutes to take</span>
          </div>
          <div className="study-field">
            <span className="field-label">Modules</span>
            <div className="study-mods">
              {withMaterial.map((m) => (
                <label key={m.id} className="quiz-check">
                  <input
                    type="checkbox"
                    checked={scope.includes(m.id)}
                    onChange={() =>
                      setPicked((prev) => {
                        const cur = prev ?? withMaterial.map((x) => x.id);
                        return cur.includes(m.id)
                          ? cur.length > 1
                            ? cur.filter((x) => x !== m.id)
                            : cur
                          : withMaterial.map((x) => x.id).filter((x) => x === m.id || cur.includes(x));
                      })
                    }
                  />
                  {m.title}
                </label>
              ))}
            </div>
          </div>
          <button
            type="button"
            className="btn btn-primary study-final-go"
            onClick={() =>
              startJob("final", () =>
                api.post<JobRef>("/api/quizzes", {
                  module_ids: scope,
                  types: p.types,
                  type_mix: p.mix,
                  count,
                  mode: "exercise",
                  exam: true,
                  role: "final",
                }),
              )
            }
          >
            <GraduationCap size={15} strokeWidth={1.75} /> Build {count}-question exam
          </button>
          <p className="study-muted study-small">
            Writing and checking takes a while: roughly 20 to 30 minutes for 40 questions. Every code
            answer is compiled and run before you see it.
          </p>
        </details>
      )}

      {data.finals.length > 1 && (
        <ul className="study-final-older">
          {data.finals.slice(1, 5).map((f) => (
            <li key={f.artifact_id}>
              <button type="button" className="link-btn" onClick={() => onPlay(f.artifact_id)}>
                {f.question_count} questions, {new Date(f.generated_at).toLocaleDateString()}
              </button>
              <span className="study-muted">{f.best_score != null ? `${Math.round(f.best_score)}%` : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}

// ── Page ───────────────────────────────────────────────────────────────

export function StudyPage() {
  const { courseId } = useParams({ from: "/courses/$courseId/study" });
  const qc = useQueryClient();
  const courses = useQuery({
    queryKey: ["courses"],
    queryFn: () => api.get<CourseOut[]>("/api/courses"),
  });
  const course = { data: courses.data?.find((c) => String(c.id) === courseId) };
  const study = useQuery({
    queryKey: ["study", courseId],
    queryFn: () => api.get<StudyOut>(`/api/courses/${courseId}/study`),
  });
  const local = useStudyJobs(courseId);
  const { add, done } = local;
  // Jobs the server knows are in flight (started on another device, or before
  // a reload) merged with the ones started here.
  const jobs = useMemo(() => {
    const server: Record<string, number> = {};
    for (const m of study.data?.modules ?? []) {
      for (const [slot, id] of Object.entries(m.pending ?? {})) {
        const key = slot.startsWith("section:")
          ? `section:${m.id}:${slot.slice(8)}`
          : `${slot}:${m.id}`;
        server[key] = id;
      }
    }
    if (study.data?.pending_final != null) server.final = study.data.pending_final;
    return { ...server, ...local.jobs };
  }, [study.data, local.jobs]);
  const [playing, setPlaying] = useState<number | null>(null);
  const [openStep, setOpenStep] = useState<number | null>(null);
  const [preset, setPreset] = useState<Preset>("output");
  const [error, setError] = useState<string | null>(null);

  const quiz = useQuery({
    queryKey: ["quiz", playing],
    queryFn: () => api.get<QuizOut>(`/api/quizzes/${playing}`),
    enabled: playing != null,
  });

  const modules = useMemo(() => study.data?.modules ?? [], [study.data]);
  const moduleTitles = useMemo(
    () => Object.fromEntries(modules.map((m) => [m.id, m.title])),
    [modules],
  );
  const doneCount = modules.filter((m) => passed(m.checkpoint)).length;
  const nextUp = modules.find((m) => m.has_material && !passed(m.checkpoint));
  const codeCourse = modules.some((m) => m.language);

  useEffect(() => {
    if (!codeCourse && study.data) setPreset("balanced");
  }, [codeCourse, study.data]);
  useEffect(() => {
    if (openStep == null && nextUp) setOpenStep(nextUp.id);
  }, [nextUp, openStep]);

  const start = useMutation({
    mutationFn: async ({ key, run }: { key: string; run: () => Promise<JobRef> }) => ({
      key,
      ref: await run(),
    }),
    onSuccess: ({ key, ref }) => {
      setError(null);
      add(key, ref.job_id);
    },
    onError: (e) => setError((e as Error).message),
  });

  function finishJob(key: string, ok: boolean) {
    done(key);
    if (!ok) setError("A generation run failed. The Activity page has the details; try again.");
    qc.invalidateQueries({ queryKey: ["study", courseId] });
    qc.invalidateQueries({ queryKey: ["summary"] });
  }

  if (playing != null) {
    if (!quiz.data) {
      return (
        <div className="study-page">
          <p className="study-muted">
            <Loader2 size={14} className="spin" /> Opening the test
          </p>
        </div>
      );
    }
    return (
      <div className="study-page study-playing">
        <ExamPlayer
          quiz={quiz.data}
          moduleTitles={moduleTitles}
          onExit={() => {
            setPlaying(null);
            qc.invalidateQueries({ queryKey: ["study", courseId] });
          }}
          onPracticeWeak={(topics, moduleIds) => {
            setPlaying(null);
            const ids = moduleIds.length ? moduleIds : quiz.data.scope_module_ids;
            start.mutate({
              key: "final",
              run: () =>
                api.post<JobRef>("/api/quizzes", {
                  module_ids: ids,
                  types: PRESETS[preset].types,
                  type_mix: PRESETS[preset].mix,
                  count: Math.min(20, Math.max(8, topics.length * 2)),
                  mode: "exercise",
                  exam: true,
                  role: "final",
                  instructions: `Drill these weak topics: ${topics.join("; ")}`,
                }),
            });
          }}
        />
      </div>
    );
  }

  return (
    <div className="study-page">
      <nav className="crumb">
        <Link to="/courses/$courseId" params={{ courseId }}>
          <ChevronLeft size={15} strokeWidth={1.5} /> {course.data?.code ?? "Course"}
        </Link>
      </nav>

      <header className="study-head">
        <h1>Study path</h1>
        <p className="study-head-sub">
          {modules.length > 0
            ? `${doneCount} of ${modules.filter((m) => m.has_material).length} topic tests passed. Read each section, check it, then take the topic test.`
            : "Lessons, section checks and topic tests, then one final mock exam."}
        </p>
        {modules.length > 0 && (
          <ol className="study-track" aria-label="Progress by module">
            {modules.map((m) => (
              <li
                key={m.id}
                className={passed(m.checkpoint) ? "ok" : m.checkpoint?.best_score != null ? "low" : ""}
                title={`${m.title}: ${scoreLabel(m.checkpoint) ?? "no topic test yet"}`}
              />
            ))}
          </ol>
        )}
      </header>

      {error && <p className="error-text">{error}</p>}
      {study.isLoading && (
        <div className="study-skeleton" aria-hidden>
          {[0, 1, 2].map((i) => (
            <div key={i} className="study-skel-row" />
          ))}
        </div>
      )}
      {study.isError && <p className="error-text">Could not load the study path.</p>}

      {study.data && (
        <div className="study-layout">
          <ol className="study-steps">
            {modules.map((m, i) => (
              <ModuleStep
                key={m.id}
                n={i + 1}
                courseId={courseId}
                module={m}
                open={openStep === m.id}
                onToggle={() => setOpenStep((v) => (v === m.id ? -1 : m.id))}
                jobs={jobs}
                startJob={(key, run) => start.mutate({ key, run })}
                finishJob={finishJob}
                onPlay={setPlaying}
                preset={preset}
              />
            ))}
            {modules.length === 0 && (
              <li className="study-muted">This course has no modules yet.</li>
            )}
          </ol>
          <FinalPanel
            data={study.data}
            jobs={jobs}
            startJob={(key, run) => start.mutate({ key, run })}
            finishJob={finishJob}
            onPlay={setPlaying}
            preset={preset}
            setPreset={setPreset}
          />
        </div>
      )}
    </div>
  );
}
