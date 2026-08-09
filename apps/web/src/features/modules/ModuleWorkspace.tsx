import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";

import { useState } from "react";

import { api, type ModuleDetail } from "../../lib/api";
import { useActiveJobs } from "../ai/common";
import { FlashcardsTab } from "../ai/FlashcardsTab";
import { GenerateAllModal } from "../ai/GenerateAllModal";
import { QuizTab } from "../ai/QuizTab";
import { SummaryTab } from "../ai/SummaryTab";
import { MaterialsTab } from "../materials/MaterialsTab";
import { NotesTab } from "../notes/NotesTab";
import "./module.css";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "materials", label: "Materials" },
  { key: "summary", label: "Summary" },
  { key: "cards", label: "Cards" },
  { key: "quiz", label: "Quiz" },
  { key: "notes", label: "Notes" },
] as const;

const JOB_LABELS: Record<string, string> = {
  generate_summary: "Summary",
  generate_flashcards: "Flashcards",
  generate_quiz: "Quiz",
};

function Overview({ module }: { module: ModuleDetail }) {
  const navigate = useNavigate();
  const [generating, setGenerating] = useState(false);
  const active = useActiveJobs(String(module.id));

  return (
    <div className="module-overview">
      <p className="overview-stats">
        {module.document_count}{" "}
        {module.document_count === 1 ? "document" : "documents"}
        {module.has_note ? " · personal notes started" : " · no notes yet"}
      </p>
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
  const { tab } = useSearch({ from: "/courses/$courseId/modules/$moduleId" });

  const detail = useQuery({
    queryKey: ["module", moduleId],
    queryFn: () => api.get<ModuleDetail>(`/api/modules/${moduleId}`),
  });
  const module = detail.data;

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

      <nav className="tab-bar" aria-label="Module sections">
        {TABS.map((t) => (
          <Link
            key={t.key}
            to="/courses/$courseId/modules/$moduleId"
            params={{ courseId, moduleId }}
            search={{ tab: t.key }}
            className={`tab${tab === t.key ? " active" : ""}`}
          >
            {t.label}
          </Link>
        ))}
      </nav>

      {module && tab === "overview" && <Overview module={module} />}
      {module && tab === "materials" && <MaterialsTab moduleId={moduleId} />}
      {module && tab === "summary" && <SummaryTab moduleId={moduleId} />}
      {module && tab === "cards" && <FlashcardsTab moduleId={moduleId} />}
      {module && tab === "quiz" && <QuizTab moduleId={moduleId} courseId={courseId} />}
      {module && tab === "notes" && <NotesTab moduleId={moduleId} />}
    </div>
  );
}
