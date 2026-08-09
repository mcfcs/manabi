import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";

import { Modal } from "../../components/Modal";
import { api, type CourseOut } from "../../lib/api";
import "./home.css";

const ACCENTS = ["#C93A2E", "#28518F", "#3E7A4E", "#B07D1F", "#6A4C93", "#1C2434"];

function CourseDialog({
  course,
  onClose,
}: {
  course: CourseOut | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [code, setCode] = useState(course?.code ?? "");
  const [name, setName] = useState(course?.name ?? "");
  const [term, setTerm] = useState(course?.term ?? "");
  const [instructor, setInstructor] = useState(course?.instructor ?? "");
  const [accent, setAccent] = useState(course?.accent_color ?? ACCENTS[1]);

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      course
        ? api.patch<CourseOut>(`/api/courses/${course.id}`, body)
        : api.post<CourseOut>("/api/courses", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["courses"] });
      onClose();
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate({
      code,
      name,
      term: term || null,
      instructor: instructor || null,
      accent_color: accent,
    });
  }

  return (
    <Modal title={course ? "Edit course" : "New course"} onClose={onClose}>
      <form className="modal-form" onSubmit={submit}>
        <div>
          <label className="field-label" htmlFor="course-code">
            Course code
          </label>
          <input
            id="course-code"
            className="input"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="CSCI 123"
            required
          />
        </div>
        <div>
          <label className="field-label" htmlFor="course-name">
            Name
          </label>
          <input
            id="course-name"
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Computer Architecture"
            required
          />
        </div>
        <div>
          <label className="field-label" htmlFor="course-term">
            Term (optional)
          </label>
          <input
            id="course-term"
            className="input"
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder="1st Sem 2026–27"
          />
        </div>
        <div>
          <label className="field-label" htmlFor="course-instructor">
            Instructor (optional)
          </label>
          <input
            id="course-instructor"
            className="input"
            value={instructor}
            onChange={(e) => setInstructor(e.target.value)}
          />
        </div>
        <div>
          <span className="field-label">Accent</span>
          <div className="accent-row">
            {ACCENTS.map((c) => (
              <button
                key={c}
                type="button"
                className={`accent-swatch${accent === c ? " selected" : ""}`}
                style={{ background: c }}
                onClick={() => setAccent(c)}
                aria-label={`Accent ${c}`}
              />
            ))}
          </div>
        </div>
        {save.isError && <p className="error-text">{(save.error as Error).message}</p>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            {course ? "Save" : "Create course"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

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

      {courses.isLoading && <div className="home-empty">Loading…</div>}
      {courses.isError && (
        <div className="home-empty">
          <p>Could not load courses. <button className="btn" onClick={() => courses.refetch()}>Retry</button></p>
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
            <Link
              key={course.id}
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
          ))}
        </div>
      )}

      {dialog && (
        <CourseDialog course={dialog.course} onClose={() => setDialog(null)} />
      )}
    </div>
  );
}
