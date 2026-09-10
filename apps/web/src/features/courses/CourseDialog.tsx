import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Loader2, Trash2 } from "lucide-react";
import { type FormEvent, useRef, useState } from "react";

import { Modal } from "../../components/Modal";
import {
  api,
  ApiError,
  type CourseOut,
  type DeleteConsequences,
} from "../../lib/api";
import { type CanvasCourse, suggestCanvasCourse } from "../../lib/canvasMatch";

const ACCENTS = [
  "#C93A2E", "#28518F", "#3E7A4E", "#B07D1F", "#6A4C93", "#1C2434", "#2E7D8F",
];

/** Prefer the server's structured message (e.g. the Canvas-link 409). */
function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const d = err.detail as { message?: unknown } | string | undefined;
    if (d && typeof d === "object" && typeof d.message === "string") return d.message;
  }
  return err instanceof Error ? err.message : "Something went wrong";
}

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
  const [units, setUnits] = useState(String(course?.units ?? 3));
  const [cutAllowance, setCutAllowance] = useState(
    course?.cut_allowance == null ? "" : String(course.cut_allowance),
  );
  const [accent, setAccent] = useState(course?.accent_color ?? ACCENTS[1]);
  const [confirming, setConfirming] = useState<DeleteConsequences | null>(null);
  const [cover, setCover] = useState(course?.cover_image_url ?? null);
  const [coverBusy, setCoverBusy] = useState(false);
  const coverInput = useRef<HTMLInputElement>(null);

  // Canvas link: the dropdown pre-selects the code match for an unlinked
  // course ("suggested"); nothing is written until Save.
  const [canvasId, setCanvasId] = useState<number | null>(null);
  const [canvasTouched, setCanvasTouched] = useState(false);
  const canvasCourses = useQuery({
    queryKey: ["canvas-courses"],
    queryFn: () => api.get<CanvasCourse[]>("/api/canvas/courses"),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const linkedId = course?.canvas_course_id ?? null;
  const suggestion =
    linkedId == null && canvasCourses.data
      ? suggestCanvasCourse(code, canvasCourses.data)
      : null;
  const effectiveCanvasId = canvasTouched ? canvasId : (linkedId ?? suggestion?.id ?? null);
  const showSuggested = !canvasTouched && linkedId == null && suggestion != null;
  const canvasUnavailable =
    canvasCourses.error instanceof ApiError && canvasCourses.error.status === 409
      ? "Canvas isn't configured (set CANVAS_BASE_URL and CANVAS_ACCESS_TOKEN in .env)."
      : "Couldn't reach Canvas right now.";
  const effectiveInList =
    effectiveCanvasId == null ||
    (canvasCourses.data ?? []).some((c) => c.id === effectiveCanvasId);

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

  async function uploadCover(fileList: FileList | null) {
    if (!course || !fileList?.[0]) return;
    setCoverBusy(true);
    try {
      const form = new FormData();
      form.append("file", fileList[0]);
      const updated = await api.postForm<CourseOut>(
        `/api/courses/${course.id}/cover`,
        form,
      );
      setCover(updated.cover_image_url);
      invalidate();
    } finally {
      setCoverBusy(false);
    }
  }

  async function removeCover() {
    if (!course) return;
    setCoverBusy(true);
    try {
      await api.delete(`/api/courses/${course.id}/cover`);
      setCover(null);
      invalidate();
    } finally {
      setCoverBusy(false);
    }
  }

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
      units: Number(units) > 0 ? Number(units) : 3,
      // Blank means "not recorded" — distinct from an allowance of zero.
      cut_allowance: cutAllowance.trim() === "" ? null : Number(cutAllowance),
      canvas_course_id: effectiveCanvasId,
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
          <label className="field-label" htmlFor="course-units">
            Units
          </label>
          <input
            id="course-units"
            className="input"
            type="number"
            inputMode="decimal"
            min="0"
            max="12"
            step="0.5"
            value={units}
            onChange={(e) => setUnits(e.target.value)}
          />
          <p className="settings-hint">How much this course weighs in the term QPI.</p>
        </div>
        <div>
          <label className="field-label" htmlFor="course-cuts">
            Allowed absences (optional)
          </label>
          <input
            id="course-cuts"
            className="input"
            type="number"
            inputMode="decimal"
            min="0"
            max="30"
            step="0.5"
            value={cutAllowance}
            onChange={(e) => setCutAllowance(e.target.value)}
            placeholder="—"
          />
          <p className="settings-hint">
            What the syllabus allows before this course is at risk. Leave blank if you would
            rather not track it; a late counts as half.
          </p>
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
          <label className="field-label" htmlFor="course-canvas">
            Canvas course (optional)
          </label>
          {canvasCourses.isLoading && (
            <p className="gen-hint">
              <Loader2 size={13} className="spin" /> Loading your Canvas courses…
            </p>
          )}
          {canvasCourses.isError && (
            <p className="gen-hint">
              {canvasUnavailable}
              {linkedId != null ? ` Currently linked to Canvas course #${linkedId}.` : ""}
            </p>
          )}
          {canvasCourses.data && (
            <>
              <select
                id="course-canvas"
                className="input"
                value={effectiveCanvasId ?? ""}
                onChange={(e) => {
                  setCanvasTouched(true);
                  setCanvasId(e.target.value ? Number(e.target.value) : null);
                }}
              >
                <option value="">Not linked</option>
                {!effectiveInList && effectiveCanvasId != null && (
                  <option value={effectiveCanvasId}>
                    Canvas course #{effectiveCanvasId} (not in your active courses)
                  </option>
                )}
                {canvasCourses.data.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.course_code ? `${c.course_code} — ` : ""}
                    {c.name.slice(0, 60)}
                  </option>
                ))}
              </select>
              <p className="gen-hint">
                {showSuggested
                  ? "Suggested from the course code — Save to confirm."
                  : effectiveCanvasId == null
                    ? "Linking enables announcements, Canvas file import and course sync."
                    : "Announcements, file import and sync use this Canvas course."}
              </p>
            </>
          )}
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
        {course && (
          <div>
            <span className="field-label">Cover image (optional)</span>
            <div className="course-cover-edit">
              {cover ? (
                <img src={cover} alt="Course cover" className="course-cover-preview" />
              ) : (
                <div className="course-cover-empty">No cover</div>
              )}
              <div className="course-cover-actions">
                <button
                  type="button"
                  className="btn"
                  disabled={coverBusy}
                  onClick={() => coverInput.current?.click()}
                >
                  <ImagePlus size={14} strokeWidth={1.75} />{" "}
                  {cover ? "Replace" : "Upload"}
                </button>
                {cover && (
                  <button
                    type="button"
                    className="btn"
                    disabled={coverBusy}
                    onClick={removeCover}
                  >
                    <Trash2 size={14} strokeWidth={1.75} /> Remove
                  </button>
                )}
              </div>
              <input
                ref={coverInput}
                type="file"
                accept="image/png,image/jpeg,image/gif,image/webp"
                hidden
                onChange={(e) => {
                  uploadCover(e.target.files);
                  e.target.value = "";
                }}
              />
            </div>
          </div>
        )}
        {save.isError && <p className="error-text">{describeError(save.error)}</p>}
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
