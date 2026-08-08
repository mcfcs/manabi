import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  FileText,
  Pencil,
  Plus,
  StickyNote,
  Trash2,
} from "lucide-react";
import { type FormEvent, useState } from "react";

import { Modal } from "../../components/Modal";
import {
  api,
  ApiError,
  type CourseOut,
  type DeleteConsequences,
  type ModuleOut,
} from "../../lib/api";
import "./course.css";

function ModuleRow({
  module,
  index,
  total,
  courseId,
  onMove,
}: {
  module: ModuleOut;
  index: number;
  total: number;
  courseId: string;
  onMove: (id: number, dir: -1 | 1) => void;
}) {
  const queryClient = useQueryClient();
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(module.title);
  const [confirming, setConfirming] = useState<DeleteConsequences | null>(null);

  const rename = useMutation({
    mutationFn: () => api.patch(`/api/modules/${module.id}`, { title }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["modules", courseId] });
      setRenaming(false);
    },
  });

  const remove = useMutation({
    mutationFn: (confirm: boolean) =>
      api.delete(`/api/modules/${module.id}?confirm=${confirm}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["modules", courseId] });
      queryClient.invalidateQueries({ queryKey: ["courses"] });
      setConfirming(null);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        setConfirming(err.detail as DeleteConsequences);
      }
    },
  });

  return (
    <div className="module-row">
      <span className="module-index">{index + 1}</span>
      {renaming ? (
        <form
          className="module-rename"
          onSubmit={(e) => {
            e.preventDefault();
            rename.mutate();
          }}
        >
          <input
            className="input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            autoFocus
          />
          <button className="btn btn-primary">Save</button>
          <button type="button" className="btn" onClick={() => setRenaming(false)}>
            Cancel
          </button>
        </form>
      ) : (
        <>
          <Link
            to="/courses/$courseId/modules/$moduleId"
            params={{ courseId, moduleId: String(module.id) }}
            search={{ tab: "overview" }}
            className="module-link"
          >
            <span className="module-title">{module.title}</span>
            <span className="module-meta">
              <FileText size={13} strokeWidth={1.5} /> {module.document_count}
              {module.has_note && (
                <>
                  {" · "}
                  <StickyNote size={13} strokeWidth={1.5} /> notes
                </>
              )}
            </span>
          </Link>
          <div className="module-actions">
            <button
              className="icon-btn"
              disabled={index === 0}
              onClick={() => onMove(module.id, -1)}
              aria-label="Move up"
            >
              <ArrowUp size={16} strokeWidth={1.5} />
            </button>
            <button
              className="icon-btn"
              disabled={index === total - 1}
              onClick={() => onMove(module.id, 1)}
              aria-label="Move down"
            >
              <ArrowDown size={16} strokeWidth={1.5} />
            </button>
            <button
              className="icon-btn"
              onClick={() => setRenaming(true)}
              aria-label="Rename"
            >
              <Pencil size={16} strokeWidth={1.5} />
            </button>
            <button
              className="icon-btn danger"
              onClick={() => remove.mutate(false)}
              aria-label="Delete"
            >
              <Trash2 size={16} strokeWidth={1.5} />
            </button>
          </div>
        </>
      )}

      {confirming && (
        <Modal title={`Delete "${module.title}"?`} onClose={() => setConfirming(null)}>
          <p className="modal-danger-text">
            This permanently deletes {confirming.documents}{" "}
            {confirming.documents === 1 ? "document" : "documents"}
            {confirming.notes ? " and your personal notes" : ""} in this module.
          </p>
          <div className="modal-actions">
            <button className="btn" onClick={() => setConfirming(null)}>
              Cancel
            </button>
            <button className="btn btn-danger" onClick={() => remove.mutate(true)}>
              Delete module
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

export function CoursePage() {
  const { courseId } = useParams({ from: "/courses/$courseId" });
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [confirmingCourse, setConfirmingCourse] =
    useState<DeleteConsequences | null>(null);

  const courses = useQuery({
    queryKey: ["courses"],
    queryFn: () => api.get<CourseOut[]>("/api/courses"),
  });
  const course = courses.data?.find((c) => String(c.id) === courseId);

  const modules = useQuery({
    queryKey: ["modules", courseId],
    queryFn: () => api.get<ModuleOut[]>(`/api/courses/${courseId}/modules`),
  });

  const addModule = useMutation({
    mutationFn: () =>
      api.post(`/api/courses/${courseId}/modules`, { title: newTitle }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["modules", courseId] });
      queryClient.invalidateQueries({ queryKey: ["courses"] });
      setNewTitle("");
      setAdding(false);
    },
  });

  const reorder = useMutation({
    mutationFn: (ids: number[]) =>
      api.put(`/api/courses/${courseId}/modules/reorder`, { ids }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["modules", courseId] }),
  });

  const removeCourse = useMutation({
    mutationFn: (confirm: boolean) =>
      api.delete(`/api/courses/${courseId}?confirm=${confirm}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["courses"] });
      navigate({ to: "/" });
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        setConfirmingCourse(err.detail as DeleteConsequences);
      }
    },
  });

  function move(id: number, dir: -1 | 1) {
    const list = modules.data ?? [];
    const ids = list.map((m) => m.id);
    const i = ids.indexOf(id);
    const j = i + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    reorder.mutate(ids);
  }

  function submitAdd(e: FormEvent) {
    e.preventDefault();
    if (newTitle.trim()) addModule.mutate();
  }

  return (
    <div className="course-page">
      <nav className="crumb">
        <Link to="/">
          <ChevronLeft size={15} strokeWidth={1.5} /> Courses
        </Link>
      </nav>

      <header className="course-head">
        <span
          className="course-head-accent"
          style={{ background: course?.accent_color ?? "var(--accent-blue)" }}
        />
        <div className="course-head-text">
          <h1>{course ? `${course.code} · ${course.name}` : "…"}</h1>
          {course?.term && <p className="course-head-meta">{course.term}</p>}
        </div>
        <button
          className="icon-btn danger course-delete"
          onClick={() => removeCourse.mutate(false)}
          aria-label="Delete course"
        >
          <Trash2 size={16} strokeWidth={1.5} />
        </button>
      </header>

      <section className="module-section">
        <div className="module-section-head">
          <h2>Modules</h2>
          <button className="btn btn-primary" onClick={() => setAdding(true)}>
            <Plus size={16} strokeWidth={2} /> Module
          </button>
        </div>

        {modules.data && modules.data.length === 0 && !adding && (
          <div className="home-empty">
            <p>No modules yet. Add "Module 1 — Introduction" to begin.</p>
          </div>
        )}

        <div className="module-list">
          {(modules.data ?? []).map((m, i) => (
            <ModuleRow
              key={m.id}
              module={m}
              index={i}
              total={modules.data?.length ?? 0}
              courseId={courseId}
              onMove={move}
            />
          ))}
        </div>

        {adding && (
          <form className="module-add" onSubmit={submitAdd}>
            <input
              className="input"
              placeholder="Module title, e.g. Module 4 — Cache"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              autoFocus
            />
            <button className="btn btn-primary" disabled={addModule.isPending}>
              Add
            </button>
            <button type="button" className="btn" onClick={() => setAdding(false)}>
              Cancel
            </button>
          </form>
        )}
      </section>

      {confirmingCourse && (
        <Modal
          title={`Delete ${course?.code ?? "course"}?`}
          onClose={() => setConfirmingCourse(null)}
        >
          <p className="modal-danger-text">
            This permanently deletes {confirmingCourse.modules ?? 0} modules,{" "}
            {confirmingCourse.documents} documents
            {confirmingCourse.notes ? `, and ${confirmingCourse.notes} notes` : ""}.
          </p>
          <div className="modal-actions">
            <button className="btn" onClick={() => setConfirmingCourse(null)}>
              Cancel
            </button>
            <button
              className="btn btn-danger"
              onClick={() => removeCourse.mutate(true)}
            >
              Delete course
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
