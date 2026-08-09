import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { Modal } from "../../components/Modal";
import {
  api,
  ApiError,
  type CourseOut,
  type DeleteConsequences,
} from "../../lib/api";

const ACCENTS = [
  "#C93A2E", "#28518F", "#3E7A4E", "#B07D1F", "#6A4C93", "#1C2434", "#2E7D8F",
];

/** Create/edit a course; editing also offers deletion (with consequences
 * confirm). Used from Home, Schedule, and the calendar day panel. */
export function CourseDialog({
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
  const [meetingUrl, setMeetingUrl] = useState(course?.meeting_url ?? "");
  const [accent, setAccent] = useState(course?.accent_color ?? ACCENTS[1]);
  const [confirming, setConfirming] = useState<DeleteConsequences | null>(null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["courses"] });
    queryClient.invalidateQueries({ queryKey: ["schedule"] });
    queryClient.invalidateQueries({ queryKey: ["calendar"] });
  };

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      course
        ? api.patch<CourseOut>(`/api/courses/${course.id}`, body)
        : api.post<CourseOut>("/api/courses", body),
    onSuccess: () => {
      invalidate();
      onClose();
    },
  });

  const remove = useMutation({
    mutationFn: (confirm: boolean) =>
      api.delete(`/api/courses/${course!.id}?confirm=${confirm}`),
    onSuccess: () => {
      invalidate();
      onClose();
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        setConfirming(err.detail as DeleteConsequences);
      }
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate({
      code,
      name,
      term: term || null,
      instructor: instructor || null,
      meeting_url: meetingUrl.trim() || null,
      accent_color: accent,
    });
  }

  if (confirming) {
    return (
      <Modal title={`Remove "${course?.code}"?`} onClose={onClose}>
        <p className="modal-danger-text">
          This deletes {confirming.modules ?? 0} module
          {(confirming.modules ?? 0) === 1 ? "" : "s"}, {confirming.documents}{" "}
          document{confirming.documents === 1 ? "" : "s"}, and{" "}
          {confirming.notes} note{confirming.notes === 1 ? "" : "s"}.
        </p>
        <div className="modal-actions">
          <button className="btn" onClick={() => setConfirming(null)}>
            Cancel
          </button>
          <button className="btn btn-danger" onClick={() => remove.mutate(true)}>
            Delete everything
          </button>
        </div>
      </Modal>
    );
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
        <div className="event-form-row">
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
        </div>
        <div>
          <label className="field-label" htmlFor="course-meet">
            Online meeting link (Google Meet / Zoom, optional)
          </label>
          <input
            id="course-meet"
            className="input"
            type="url"
            value={meetingUrl}
            onChange={(e) => setMeetingUrl(e.target.value)}
            placeholder="https://meet.google.com/…"
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
          {course && (
            <button
              type="button"
              className="btn btn-danger event-delete"
              onClick={() => remove.mutate(false)}
            >
              Delete…
            </button>
          )}
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
