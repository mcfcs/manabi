import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { api, type GradesOverviewOut } from "../../lib/api";
import { GradeValue, useGradesHidden } from "./GradeValue";
import { fmtPercent, fmtQpi, fmtUnits } from "./grades";
import "./grades.css";

/** Every course's standing side by side, plus the term QPI. */
export function GradesPage() {
  const hidden = useGradesHidden();
  const overview = useQuery({
    queryKey: ["grades-overview"],
    queryFn: () => api.get<GradesOverviewOut>("/api/grades"),
  });

  const data = overview.data;
  const courses = data?.courses ?? [];
  const configured = courses.filter((c) => c.component_count > 0);

  return (
    <div className="grades-page">
      <header className="grades-page-head">
        <h1>Grades</h1>
        {hidden && <span className="badge grades-hidden-badge">hidden</span>}
      </header>

      {overview.isLoading && <p className="gen-hint">Loading…</p>}

      {data && (
        <div className="grades-qpi">
          <div className="grades-qpi-figure">
            <GradeValue className="grades-qpi-value">{fmtQpi(data.qpi)}</GradeValue>
            <span className="grades-qpi-label">term QPI</span>
          </div>
          <p className="grades-qpi-meta">
            {data.qpi == null
              ? "No course has a letter yet — add a syllabus breakdown and its scheme to see a QPI."
              : `Across ${fmtUnits(data.graded_units)} with a letter, of ${fmtUnits(
                  data.total_units,
                )} this term.`}
          </p>
        </div>
      )}

      {data && configured.length === 0 && (
        <div className="home-empty">
          <p>
            No course has a grading breakdown yet. Open a course and add its sections from the
            syllabus — weights, scores, and the letter cutoffs it uses.
          </p>
        </div>
      )}

      <div className="grades-course-list">
        {courses.map((c) => (
          <Link
            key={c.course_id}
            to="/courses/$courseId"
            params={{ courseId: String(c.course_id) }}
            className="grades-course-row"
          >
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
          </Link>
        ))}
      </div>
    </div>
  );
}
