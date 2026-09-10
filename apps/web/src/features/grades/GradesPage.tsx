import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, RefreshCw } from "lucide-react";
import { useState } from "react";

import {
  api,
  type CourseGradeSummaryOut,
  type GradesOverviewOut,
  type SyncAllOut,
} from "../../lib/api";
import { CourseGradesEditor } from "./CourseGradesEditor";
import { GradeValue, useGradesHidden } from "./GradeValue";
import { fmtPercent, fmtQpi, fmtUnits } from "./grades";
import "./grades.css";

/** The one place grades live: every course's standing, the term QPI, and the
 * breakdown editor for whichever course is open. Grades deliberately never
 * appear on the course page. */
export function GradesPage() {
  const hidden = useGradesHidden();
  const qc = useQueryClient();
  const [open, setOpen] = useState<number | null>(null);
  const [syncNote, setSyncNote] = useState<string | null>(null);
  const overview = useQuery({
    queryKey: ["grades-overview"],
    queryFn: () => api.get<GradesOverviewOut>("/api/grades"),
  });

  // Canvas tasks already sync every course in one pass, and automatically.
  // Grades had neither, so keeping a term current meant expanding each row.
  const syncAll = useMutation({
    mutationFn: () => api.post<SyncAllOut>("/api/grades/sync-all", {}),
    onSuccess: (r) => {
      const names = Object.entries(r.courses)
        .map(([code, n]) => `${code} ${n}`)
        .join(", ");
      const failed = Object.keys(r.failed);
      setSyncNote(
        [
          r.updated > 0
            ? `Updated ${r.updated} score${r.updated === 1 ? "" : "s"}${names ? ` — ${names}` : ""}.`
            : "Every linked score was already current.",
          r.still_ungraded > 0 ? `${r.still_ungraded} still ungraded in Canvas.` : "",
          failed.length ? `Could not reach: ${failed.join(", ")}.` : "",
        ]
          .filter(Boolean)
          .join(" "),
      );
      qc.invalidateQueries({ queryKey: ["grades-overview"] });
      qc.invalidateQueries({ queryKey: ["course-grades"] });
    },
  });

  const data = overview.data;
  const courses = data?.courses ?? [];
  const configured = courses.filter((c) => c.component_count > 0);

  return (
    <div className="grades-page">
      <header className="grades-page-head">
        <h1>Grades</h1>
        {hidden && <span className="badge grades-hidden-badge">hidden</span>}
        <button
          className="btn btn-sm grades-sync-all"
          onClick={() => syncAll.mutate()}
          disabled={syncAll.isPending}
          title="Refresh linked Canvas scores across every course"
        >
          <RefreshCw
            size={13}
            strokeWidth={1.75}
            className={syncAll.isPending ? "spin" : undefined}
          />
          {syncAll.isPending ? "Syncing…" : "Sync all"}
        </button>
      </header>

      {syncNote && <p className="grades-sync-note">{syncNote}</p>}

      {overview.isLoading && <p className="gen-hint">Loading…</p>}

      {data && (
        <div className="grades-qpi">
          <div className="grades-qpi-figure">
            <GradeValue className="grades-qpi-value">{fmtQpi(data.qpi)}</GradeValue>
            <span className="grades-qpi-label">term QPI</span>
          </div>
          <p className="grades-qpi-meta">
            {data.qpi == null
              ? "No course has a letter yet — open one below, add its syllabus breakdown and set its scheme."
              : `Across ${fmtUnits(data.graded_units)} with a letter, of ${fmtUnits(
                  data.total_units,
                )} this term.`}
          </p>
        </div>
      )}

      {data && configured.length === 0 && (
        <p className="grades-page-hint">
          Open a course to add its sections from the syllabus — the weights, the scores, and the
          letter cutoffs it uses.
        </p>
      )}

      <div className="grades-course-list">
        {courses.map((c) => (
          <CourseRow
            key={c.course_id}
            course={c}
            expanded={open === c.course_id}
            onToggle={() => setOpen((cur) => (cur === c.course_id ? null : c.course_id))}
          />
        ))}
      </div>
    </div>
  );
}

function CourseRow({
  course: c,
  expanded,
  onToggle,
}: {
  course: CourseGradeSummaryOut;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <article className={`grades-course${expanded ? " expanded" : ""}`}>
      <button className="grades-course-row" onClick={onToggle} aria-expanded={expanded}>
        {expanded ? (
          <ChevronDown size={15} strokeWidth={1.75} className="grades-course-chevron" />
        ) : (
          <ChevronRight size={15} strokeWidth={1.75} className="grades-course-chevron" />
        )}
        <span
          className="grades-course-dot"
          style={{ background: c.accent_color ?? "var(--accent-blue)" }}
        />
        <span className="grades-course-text">
          <span className="grades-course-code">{c.code}</span>
          <span className="grades-course-meta">
            {fmtUnits(c.units)}
            {c.component_count > 0
              ? ` · ${c.component_count} section${c.component_count === 1 ? "" : "s"}`
              : " · no breakdown yet"}
            {c.component_count > 0 && c.counted_weight < c.total_weight
              ? ` · ${fmtPercent(c.total_weight - c.counted_weight)} still to come`
              : ""}
          </span>
        </span>
        {c.percent != null && (
          <GradeValue className="grades-course-percent">{fmtPercent(c.percent)}</GradeValue>
        )}
        {c.letter ? (
          <GradeValue className="grades-course-letter">{c.letter}</GradeValue>
        ) : (
          <span className="grades-course-letter empty" title="Set the scheme to see a letter">
            {c.component_count > 0 && !c.has_cutoffs ? "no scheme" : "—"}
          </span>
        )}
      </button>

      {expanded && <CourseGradesEditor courseId={String(c.course_id)} />}
    </article>
  );
}
