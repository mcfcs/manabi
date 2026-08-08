import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";

import { api, type ModuleDetail } from "../../lib/api";
import { MaterialsTab } from "../materials/MaterialsTab";
import { NotesTab } from "../notes/NotesTab";
import "./module.css";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "materials", label: "Materials" },
  { key: "notes", label: "Notes" },
] as const;

const FUTURE_TABS = ["Summary", "Cards", "Quiz"];

function Overview({ module }: { module: ModuleDetail }) {
  const navigate = useNavigate();
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
      <p className="overview-hint">
        Summaries, flashcards, and quizzes arrive in the next increment — they
        will be generated from the materials you upload here.
      </p>
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
        {FUTURE_TABS.map((label) => (
          <span key={label} className="tab disabled" title="Next increment">
            {label}
          </span>
        ))}
      </nav>

      {module && tab === "overview" && <Overview module={module} />}
      {module && tab === "materials" && <MaterialsTab moduleId={moduleId} />}
      {module && tab === "notes" && <NotesTab moduleId={moduleId} />}
    </div>
  );
}
