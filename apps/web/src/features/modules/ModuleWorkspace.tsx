import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { ChevronLeft, PanelRight } from "lucide-react";

import { useEffect, useRef, useState } from "react";

import { api, type ModuleDetail } from "../../lib/api";
import { trackRecentModule } from "../../lib/recents";
import {
  type PanelKind,
  useFloatingPanels,
} from "../panels/FloatingPanels";
import { useActiveJobs } from "../ai/common";
import { FlashcardsTab } from "../ai/FlashcardsTab";
import { GenerateAllModal } from "../ai/GenerateAllModal";
import { ChatTab } from "../chat/ChatTab";
import { QuizTab } from "../ai/QuizTab";
import { SummaryTab } from "../ai/SummaryTab";
import { MaterialsTab } from "../materials/MaterialsTab";
import { NotesTab } from "../notes/NotesTab";
import { TeacherTab } from "../teacher/TeacherTab";
import "./module.css";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "materials", label: "Materials" },
  { key: "summary", label: "Summary" },
  { key: "cards", label: "Cards" },
  { key: "quiz", label: "Quiz" },
  { key: "teacher", label: "Teacher" },
  { key: "chat", label: "Chat" },
  { key: "notes", label: "Notes" },
] as const;

// Tabs that can pop out into a floating panel.
const PANELABLE: Partial<Record<(typeof TABS)[number]["key"], PanelKind>> = {
  materials: "materials",
  summary: "summary",
  chat: "chat",
  notes: "notes",
};

const JOB_LABELS: Record<string, string> = {
  teach_module: "Lecture",
  synthesize_lecture: "Lecture audio",
  generate_summary: "Summary",
  generate_flashcards: "Flashcards",
  generate_quiz: "Quiz",
};

function Overview({ module }: { module: ModuleDetail }) {
  const navigate = useNavigate();
  const [generating, setGenerating] = useState(false);
  const active = useActiveJobs(String(module.id));

  const summary = useQuery({
    queryKey: ["summary", String(module.id)],
    queryFn: () =>
      api.get<import("../../lib/api").SummaryOut | null>(
        `/api/modules/${module.id}/summary`,
      ),
    staleTime: 30_000,
  });
  const terms = summary.data?.key_terms ?? [];

  function open(tab: "materials" | "summary" | "cards" | "quiz" | "notes") {
    navigate({
      to: "/courses/$courseId/modules/$moduleId",
      params: {
        courseId: String(module.course_id),
        moduleId: String(module.id),
      },
      search: { tab },
    });
  }

  return (
    <div className="module-overview">
      <div className="stat-tiles">
        <button className="stat-tile" onClick={() => open("materials")}>
          <span className="stat-value">{module.document_count}</span>
          <span className="stat-label">
            {module.document_count === 1 ? "material" : "materials"}
            {module.page_count > 0 && ` · ${module.page_count} pages`}
          </span>
        </button>
        <button className="stat-tile" onClick={() => open("cards")}>
          <span className="stat-value">{module.card_count}</span>
          <span className="stat-label">flashcards</span>
        </button>
        <button className="stat-tile" onClick={() => open("quiz")}>
          <span className="stat-value">{module.quiz_count}</span>
          <span className="stat-label">
            {module.quiz_count === 1 ? "quiz" : "quizzes"}
            {module.best_quiz_score != null && ` · best ${module.best_quiz_score}%`}
          </span>
        </button>
        <button className="stat-tile" onClick={() => open("notes")}>
          <span className="stat-value">{module.has_note ? "✎" : "—"}</span>
          <span className="stat-label">
            {module.note_updated_at
              ? `notes · ${new Date(module.note_updated_at).toLocaleDateString()}`
              : "no notes yet"}
          </span>
        </button>
      </div>

      <div className="overview-status">
        <button className="overview-status-row" onClick={() => open("summary")}>
          <span>Summary</span>
          {module.summary_state === "none" && (
            <span className="badge stale">not generated</span>
          )}
          {module.summary_state === "current" && (
            <span className="badge fresh">current</span>
          )}
          {module.summary_state === "outdated" && (
            <span className="badge stale">materials changed</span>
          )}
          {summary.data?.coverage && (
            <span className="gen-head-meta">
              cites {summary.data.coverage.cited}/{summary.data.coverage.total}
            </span>
          )}
        </button>
        {terms.length > 0 && (
          <div className="overview-terms">
            {terms.slice(0, 8).map((t, i) => (
              <button key={i} className="term-chip" onClick={() => open("summary")}>
                {t.term}
              </button>
            ))}
            {terms.length > 8 && (
              <span className="gen-head-meta">+{terms.length - 8} more</span>
            )}
          </div>
        )}
      </div>

      <div className="overview-actions">
        <button
          className="btn btn-primary"
          onClick={() => setGenerating(true)}
          disabled={(active.data?.length ?? 0) > 0}
        >
          Generate study kit
        </button>
        <button
          className="btn"
          onClick={() =>
            navigate({
              to: "/courses/$courseId/modules/$moduleId",
              params: {
                courseId: String(module.course_id),
                moduleId: String(module.id),
              },
              search: { tab: "materials" },
            })
          }
        >
          Upload materials
        </button>
        <button
          className="btn"
          onClick={() =>
            navigate({
              to: "/courses/$courseId/modules/$moduleId",
              params: {
                courseId: String(module.course_id),
                moduleId: String(module.id),
              },
              search: { tab: "notes" },
            })
          }
        >
          Open notes
        </button>
      </div>

      {(active.data?.length ?? 0) > 0 && (
        <div className="overview-jobs">
          {active.data!.map((j) => (
            <div key={j.job_id} className="overview-job">
              <span className="overview-job-type">
                {JOB_LABELS[j.job_type] ?? j.job_type}
              </span>
              <span className="overview-job-note">
                {j.status === "queued" ? "queued" : (j.progress_note ?? "running…")}
              </span>
            </div>
          ))}
        </div>
      )}

      <p className="overview-hint">
        Your notes guide what the AI emphasizes — they are never treated as
        source material.
      </p>

      {generating && (
        <GenerateAllModal
          moduleId={String(module.id)}
          onClose={() => setGenerating(false)}
        />
      )}
    </div>
  );
}

export function ModuleWorkspace() {
  const { courseId, moduleId } = useParams({
    from: "/courses/$courseId/modules/$moduleId",
  });
  const { tab, note } = useSearch({ from: "/courses/$courseId/modules/$moduleId" });

  const detail = useQuery({
    queryKey: ["module", moduleId],
    queryFn: () => api.get<ModuleDetail>(`/api/modules/${moduleId}`),
  });
  const module = detail.data;
  const { open } = useFloatingPanels();

  useEffect(() => {
    if (module) {
      trackRecentModule({
        moduleId: module.id,
        courseId: module.course_id,
        title: `${module.course_code} · ${module.title}`,
      });
    }
  }, [module]);

  // Keep the active tab visible in the horizontally-scrollable bar on mobile.
  const tabBarRef = useRef<HTMLElement>(null);
  useEffect(() => {
    tabBarRef.current
      ?.querySelector(".tab.active")
      ?.scrollIntoView({ inline: "center", block: "nearest" });
  }, [tab]);

  return (
    <div className="module-page">
      <nav className="crumb">
        <Link to="/courses/$courseId" params={{ courseId }}>
          <ChevronLeft size={15} strokeWidth={1.5} />
          {module?.course_code ?? "Course"}
        </Link>
      </nav>

      <header className="module-head">
        <span
          className="course-head-accent"
          style={{
            background: module?.course_accent_color ?? "var(--accent-blue)",
          }}
        />
        <h1>{module?.title ?? "…"}</h1>
      </header>

      <nav className="tab-bar" aria-label="Module sections" ref={tabBarRef}>
        {TABS.map((t) => {
          const kind = PANELABLE[t.key];
          return (
            <span key={t.key} className="tab-wrap">
              <Link
                to="/courses/$courseId/modules/$moduleId"
                params={{ courseId, moduleId }}
                search={{ tab: t.key }}
                className={`tab${tab === t.key ? " active" : ""}`}
              >
                {t.label}
              </Link>
              {kind && module && (
                <button
                  className="tab-popout"
                  title={`Open ${t.label} in a floating panel`}
                  aria-label={`Open ${t.label} in a floating panel`}
                  onClick={() =>
                    open({
                      kind,
                      moduleId,
                      courseId,
                      title: `${module.course_code} · ${module.title}`,
                    })
                  }
                >
                  <PanelRight size={12} strokeWidth={1.75} />
                </button>
              )}
            </span>
          );
        })}
      </nav>

      {module && tab === "overview" && <Overview module={module} />}
      {module && tab === "materials" && <MaterialsTab moduleId={moduleId} />}
      {module && tab === "summary" && <SummaryTab moduleId={moduleId} />}
      {module && tab === "cards" && <FlashcardsTab moduleId={moduleId} />}
      {module && tab === "quiz" && <QuizTab moduleId={moduleId} courseId={courseId} />}
      {module && tab === "teacher" && <TeacherTab moduleId={moduleId} />}
      {module && tab === "chat" && <ChatTab moduleId={moduleId} />}
      {module && tab === "notes" && (
        <NotesTab moduleId={moduleId} initialNoteId={note} />
      )}
    </div>
  );
}
