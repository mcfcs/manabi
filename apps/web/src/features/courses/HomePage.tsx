import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ExternalLink, Pencil, Plus } from "lucide-react";
import { useState } from "react";

import { api, type CourseOut } from "../../lib/api";
import { Announcements } from "./Announcements";
import { CourseDialog } from "./CourseDialog";
import { HomeWidgets } from "./HomeWidgets";
import "./home.css";

export function HomePage() {
  const [dialog, setDialog] = useState<null | { course: CourseOut | null }>(null);
  const courses = useQuery({
    queryKey: ["courses"],
    queryFn: () => api.get<CourseOut[]>("/api/courses"),
  });

  return (
    <div className="home">
      <header className="home-head">
        <h1>Your Courses</h1>
        <button
          className="btn btn-primary"
          onClick={() => setDialog({ course: null })}
        >
          <Plus size={16} strokeWidth={2} /> New course
        </button>
      </header>

      <HomeWidgets />
      <Announcements />

      {courses.isLoading && <div className="home-empty">Loading…</div>}
      {courses.isError && (
        <div className="home-empty">
          <p>Could not load courses — is the server running?</p>
        </div>
      )}
      {courses.data && courses.data.length === 0 && (
        <div className="home-empty">
          <p>
            No courses yet. Create your first course to start organizing your
            study materials.
          </p>
        </div>
      )}

      {courses.data && courses.data.length > 0 && (
        <div className="course-grid">
          {courses.data.map((course) => (
            <div key={course.id} className="course-card-wrap">
              <Link
                to="/courses/$courseId"
                params={{ courseId: String(course.id) }}
                className="course-card"
              >
                <span
                  className="course-accent"
                  style={{ background: course.accent_color ?? "var(--accent-blue)" }}
                />
                <div className="course-card-body">
                  <span className="course-code">{course.code}</span>
                  <span className="course-name">{course.name}</span>
                  <span className="course-meta">
                    {course.module_count}{" "}
                    {course.module_count === 1 ? "module" : "modules"}
                    {course.document_count > 0 && ` · ${course.document_count} docs`}
                    {course.card_count > 0 && ` · ${course.card_count} cards`}
                    {course.term ? ` · ${course.term}` : ""}
                  </span>
                </div>
              </Link>
              <div className="course-card-actions">
                <button
                  className="icon-btn"
                  onClick={() => setDialog({ course })}
                  aria-label={`Edit ${course.code}`}
                  title="Edit course (meeting link, color, delete…)"
                >
                  <Pencil size={13} strokeWidth={1.5} />
                </button>
                {course.canvas_url && (
                  <a
                    className="icon-btn"
                    href={course.canvas_url}
                    target="_blank"
                    rel="noreferrer"
                    aria-label={`Open ${course.code} in Canvas`}
                    title="Open in Canvas"
                  >
                    <ExternalLink size={13} strokeWidth={1.5} />
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {dialog && (
        <CourseDialog course={dialog.course} onClose={() => setDialog(null)} />
      )}
    </div>
  );
}
