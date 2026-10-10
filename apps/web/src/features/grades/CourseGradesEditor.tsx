import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  CloudDownload,
  ExternalLink,
  Loader2,
  Pencil,
  Plus,
  SlidersHorizontal,
  Trash2,
} from "lucide-react";
import { type FormEvent, useState } from "react";

import {
  api,
  ApiError,
  type CourseGradesOut,
  type GradeComponentOut,
  type GradeItemOut,
} from "../../lib/api";
import { CanvasLinkPicker } from "./CanvasLinkPicker";
import { GradeValue } from "./GradeValue";
import { fmtPercent, fmtScore, targetSentence, weightWarning } from "./grades";
import { SchemeEditor } from "./SchemeEditor";

/**
 * One course's grading breakdown, edited in place. Lives inside the Grades
 * page (grades deliberately never appear on the course page). The course's
 * own row carries the headline percentage, so this body starts at the detail.
 */
export function CourseGradesEditor({ courseId }: { courseId: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [addingComponent, setAddingComponent] = useState(false);
  const [name, setName] = useState("");
  const [weight, setWeight] = useState("");
  const [editingScheme, setEditingScheme] = useState(false);
  const [linkingTo, setLinkingTo] = useState<GradeComponentOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const grades = useQuery({
    queryKey: ["grades", courseId],
    queryFn: () => api.get<CourseGradesOut>(`/api/courses/${courseId}/grades`),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["grades", courseId] });
    queryClient.invalidateQueries({ queryKey: ["grades-overview"] });
  };

  const addComponent = useMutation({
    mutationFn: () =>
      api.post(`/api/courses/${courseId}/grades/components`, {
        name,
        weight: Number(weight),
      }),
    onSuccess: () => {
      setName("");
      setWeight("");
      setAddingComponent(false);
      setError(null);
      invalidate();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not add that section"),
  });

  const removeComponent = useMutation({
    mutationFn: (id: number) => api.delete(`/api/grades/components/${id}`),
    onSuccess: invalidate,
  });

  const sync = useMutation({
    mutationFn: () => api.post<{ updated: number }>(`/api/courses/${courseId}/grades/sync`),
    onSuccess: invalidate,
    onError: (e) => setError(e instanceof ApiError ? e.message : "Canvas sync failed"),
  });

  // Reorder: renumber every section so positions stay distinct (older rows
  // could share a position, which made a single swap a no-op).
  const move = useMutation({
    mutationFn: async ({ id, dir }: { id: number; dir: -1 | 1 }) => {
      const ids = (grades.data?.components ?? []).map((c) => c.id);
      const i = ids.indexOf(id);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= ids.length) return;
      [ids[i], ids[j]] = [ids[j], ids[i]];
      await Promise.all(
        ids.map((cid, position) =>
          api.patch(`/api/grades/components/${cid}`, { position }),
        ),
      );
    },
    onSettled: invalidate,
  });

  const g = grades.data;
  const sections = (g?.components ?? []).map((c) => ({ id: c.id, name: c.name }));
  if (!g) {
    return (
      <div className="grades-editor">
        <p className="gen-hint">
          <Loader2 size={13} className="spin" /> Loading…
        </p>
      </div>
    );
  }

  const empty = g.components.length === 0;
  const warning = weightWarning(g.total_weight);
  const remaining = g.total_weight - g.counted_weight;
  const nextTarget = g.targets[0];

  function submitComponent(e: FormEvent) {
    e.preventDefault();
    if (name.trim() && Number(weight) > 0) addComponent.mutate();
  }

  return (
    <div className="grades-editor">
      {empty ? (
        <p className="grades-editor-hint">
          Add the sections from this course's syllabus — Participation 10%, Quizzes 30% and so
          on. Only sections with a grade count toward your standing, so an untouched one never
          drags it down.
        </p>
      ) : (
        <>
          <div className="grades-editor-meta">
            {g.percent == null ? (
              <span>Nothing graded yet.</span>
            ) : (
              <span>
                from {fmtPercent(g.counted_weight)} of the syllabus
                {remaining > 0 ? ` · ${fmtPercent(remaining)} still to come` : " · all graded"}
              </span>
            )}
            {!g.cutoffs && <span className="grades-need-scheme">Set the scheme to see a letter.</span>}
          </div>
          <div className="grades-weightbar" aria-hidden>
            {g.components.map((c) => (
              <span
                key={c.id}
                className={`grades-weightbar-part${c.percent == null ? " pending" : ""}`}
                style={{ flexGrow: c.weight }}
                title={`${c.name} · ${fmtPercent(c.weight)}`}
              />
            ))}
          </div>
        </>
      )}

      {nextTarget && g.cutoffs && (
        <p className="grades-target">
          <GradeValue>{targetSentence(nextTarget, remaining)}</GradeValue>
        </p>
      )}
      {warning && <p className="grades-warning">{warning}</p>}

      <div className="grades-components">
        {g.components.map((c) => (
          <ComponentRow
            key={c.id}
            component={c}
            sections={sections}
            onMove={(dir) => move.mutate({ id: c.id, dir })}
            expanded={open.has(c.id)}
            canLinkCanvas={g.canvas_course_id != null}
            onToggle={() =>
              setOpen((prev) => {
                const next = new Set(prev);
                if (next.has(c.id)) next.delete(c.id);
                else next.add(c.id);
                return next;
              })
            }
            onLink={() => setLinkingTo(c)}
            onRemove={() => removeComponent.mutate(c.id)}
            onChanged={invalidate}
          />
        ))}
      </div>

      {addingComponent ? (
        <form className="grades-add" onSubmit={submitComponent}>
          <input
            className="input"
            placeholder="Section (e.g. Quizzes)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
          <div className="grades-add-weight">
            <input
              className="input"
              type="number"
              inputMode="decimal"
              min="0.1"
              max="100"
              step="0.1"
              placeholder="30"
              value={weight}
              onChange={(e) => setWeight(e.target.value)}
            />
            <span>% of the grade</span>
          </div>
          <div className="grades-add-actions">
            <button className="btn btn-primary" disabled={addComponent.isPending}>
              Add section
            </button>
            <button type="button" className="btn" onClick={() => setAddingComponent(false)}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <div className="grades-editor-actions">
          <button className="btn" onClick={() => setAddingComponent(true)}>
            <Plus size={15} strokeWidth={2} /> Add a section
          </button>
          <button className="btn" onClick={() => setEditingScheme(true)}>
            <SlidersHorizontal size={14} strokeWidth={1.75} />{" "}
            {g.cutoffs ? "Scheme" : "Set scheme"}
          </button>
          {g.canvas_course_id && !empty && (
            <button
              className="btn"
              onClick={() => sync.mutate()}
              disabled={sync.isPending}
              title="Refresh linked Canvas scores"
            >
              {sync.isPending ? (
                <Loader2 size={14} className="spin" />
              ) : (
                <CloudDownload size={14} strokeWidth={1.75} />
              )}{" "}
              Sync grades
            </button>
          )}
          <Link
            to="/courses/$courseId"
            params={{ courseId }}
            className="btn grades-open-course"
            title="Open the course"
          >
            <ExternalLink size={14} strokeWidth={1.75} /> Course
          </Link>
        </div>
      )}

      {error && <p className="error-text">{error}</p>}

      {editingScheme && <SchemeEditor grades={g} onClose={() => setEditingScheme(false)} />}
      {linkingTo && (
        <CanvasLinkPicker
          courseId={g.course_id}
          componentId={linkingTo.id}
          componentName={linkingTo.name}
          onClose={() => setLinkingTo(null)}
        />
      )}
    </div>
  );
}

function ComponentRow({
  component,
  sections,
  expanded,
  canLinkCanvas,
  onToggle,
  onLink,
  onRemove,
  onMove,
  onChanged,
}: {
  component: GradeComponentOut;
  sections: { id: number; name: string }[];
  expanded: boolean;
  canLinkCanvas: boolean;
  onToggle: () => void;
  onLink: () => void;
  onRemove: () => void;
  onMove: (dir: -1 | 1) => void;
  onChanged: () => void;
}) {
  const [renaming, setRenaming] = useState(false);
  const [newName, setNewName] = useState(component.name);
  const [newWeight, setNewWeight] = useState(String(component.weight));
  const [editError, setEditError] = useState<string | null>(null);
  const saveSection = useMutation({
    mutationFn: () =>
      api.patch(`/api/grades/components/${component.id}`, {
        name: newName,
        weight: Number(newWeight),
      }),
    onSuccess: () => {
      setRenaming(false);
      onChanged();
    },
    onError: (e) =>
      setEditError(e instanceof ApiError ? e.message : "Could not save that section"),
  });
  const index = sections.findIndex((s) => s.id === component.id);
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [earned, setEarned] = useState("");
  const [possible, setPossible] = useState("");
  const [asPercent, setAsPercent] = useState(false);

  const addItem = useMutation({
    mutationFn: () =>
      api.post(`/api/grades/components/${component.id}/items`, {
        title,
        ...(asPercent
          ? { percent: earned === "" ? null : Number(earned) }
          : {
              earned: earned === "" ? null : Number(earned),
              possible: possible === "" ? null : Number(possible),
            }),
      }),
    onSuccess: () => {
      setTitle("");
      setEarned("");
      setPossible("");
      setAdding(false);
      onChanged();
    },
  });

  const removeItem = useMutation({
    mutationFn: (id: number) => api.delete(`/api/grades/items/${id}`),
    onSuccess: onChanged,
  });

  const valid = title.trim() && (asPercent ? earned !== "" : possible !== "");

  return (
    <article className={`grade-component${expanded ? " expanded" : ""}`}>
      <button className="grade-component-head" onClick={onToggle}>
        {expanded ? (
          <ChevronDown size={15} strokeWidth={1.75} />
        ) : (
          <ChevronRight size={15} strokeWidth={1.75} />
        )}
        <span className="grade-component-name">{component.name}</span>
        <span className="grade-component-weight mono">{fmtPercent(component.weight)}</span>
        <GradeValue className="grade-component-percent">
          {component.percent == null ? "—" : fmtPercent(component.percent)}
        </GradeValue>
        <span className="grade-component-count">
          {component.item_count === 0
            ? "no scores yet"
            : `${component.graded_count}/${component.item_count} graded`}
        </span>
      </button>

      {expanded && (
        <div className="grade-component-body">
          {component.items.map((item) => (
            <ItemRow
              key={item.id}
              item={item}
              componentId={component.id}
              sections={sections}
              onRemove={() => removeItem.mutate(item.id)}
              onChanged={onChanged}
            />
          ))}
          {component.items.length === 0 && (
            <p className="gen-hint">No scores in this section yet.</p>
          )}

          {adding ? (
            <form
              className="grade-item-form"
              onSubmit={(e) => {
                e.preventDefault();
                if (valid) addItem.mutate();
              }}
            >
              <input
                className="input"
                placeholder="Score name (e.g. Quiz 1)"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                autoFocus
              />
              <div className="grade-item-form-nums">
                <input
                  className="input"
                  type="number"
                  inputMode="decimal"
                  step="0.01"
                  placeholder={asPercent ? "95" : "18"}
                  value={earned}
                  onChange={(e) => setEarned(e.target.value)}
                />
                {asPercent ? (
                  <span className="grade-item-form-sep">%</span>
                ) : (
                  <>
                    <span className="grade-item-form-sep">/</span>
                    <input
                      className="input"
                      type="number"
                      inputMode="decimal"
                      step="0.01"
                      min="0.01"
                      placeholder="20"
                      value={possible}
                      onChange={(e) => setPossible(e.target.value)}
                    />
                  </>
                )}
                <button
                  type="button"
                  className={`btn grade-item-mode${asPercent ? " active" : ""}`}
                  onClick={() => setAsPercent((v) => !v)}
                  title="Switch between points and a straight percentage"
                >
                  {asPercent ? "percent" : "points"}
                </button>
              </div>
              <div className="grades-add-actions">
                <button className="btn btn-primary" disabled={!valid || addItem.isPending}>
                  Add score
                </button>
                <button type="button" className="btn" onClick={() => setAdding(false)}>
                  Cancel
                </button>
              </div>
            </form>
          ) : renaming ? (
            <form
              className="grades-add"
              onSubmit={(e) => {
                e.preventDefault();
                if (newName.trim() && Number(newWeight) > 0) saveSection.mutate();
              }}
            >
              <input
                className="input"
                aria-label="Section name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                autoFocus
              />
              <div className="grades-add-weight">
                <input
                  className="input"
                  type="number"
                  inputMode="decimal"
                  min="0.1"
                  max="100"
                  step="0.1"
                  aria-label="Weight"
                  value={newWeight}
                  onChange={(e) => setNewWeight(e.target.value)}
                />
                <span>% of the grade</span>
              </div>
              {editError && <p className="error-text">{editError}</p>}
              <div className="grades-add-actions">
                <button className="btn btn-primary" disabled={saveSection.isPending}>
                  Save section
                </button>
                <button type="button" className="btn" onClick={() => setRenaming(false)}>
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <div className="grade-component-actions">
              <button className="btn" onClick={() => setAdding(true)}>
                <Plus size={14} strokeWidth={2} /> Add a score
              </button>
              {canLinkCanvas && (
                <button className="btn" onClick={onLink}>
                  <CloudDownload size={14} strokeWidth={1.75} /> Add from Canvas
                </button>
              )}
              <button
                className="icon-btn"
                onClick={() => {
                  setNewName(component.name);
                  setNewWeight(String(component.weight));
                  setEditError(null);
                  setRenaming(true);
                }}
                aria-label={`Edit ${component.name}`}
                title="Rename or reweight this section"
              >
                <Pencil size={14} strokeWidth={1.5} />
              </button>
              <button
                className="icon-btn"
                onClick={() => onMove(-1)}
                disabled={index <= 0}
                aria-label={`Move ${component.name} up`}
                title="Move up"
              >
                <ArrowUp size={14} strokeWidth={1.75} />
              </button>
              <button
                className="icon-btn"
                onClick={() => onMove(1)}
                disabled={index < 0 || index >= sections.length - 1}
                aria-label={`Move ${component.name} down`}
                title="Move down"
              >
                <ArrowDown size={14} strokeWidth={1.75} />
              </button>
              <button
                className="icon-btn danger"
                onClick={() => {
                  const n = component.item_count;
                  if (
                    window.confirm(
                      `Remove "${component.name}"${n ? ` and its ${n} score${n === 1 ? "" : "s"}` : ""}?`,
                    )
                  )
                    onRemove();
                }}
                aria-label={`Remove ${component.name}`}
                title="Remove this section"
              >
                <Trash2 size={15} strokeWidth={1.5} />
              </button>
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function ItemRow({
  item,
  componentId,
  sections,
  onRemove,
  onChanged,
}: {
  item: GradeItemOut;
  componentId: number;
  sections: { id: number; name: string }[];
  onRemove: () => void;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(item.title);
  const [asPercent, setAsPercent] = useState(item.percent != null);
  const [earned, setEarned] = useState(
    String(item.percent ?? item.earned ?? ""),
  );
  const [possible, setPossible] = useState(String(item.possible ?? ""));
  const [section, setSection] = useState(componentId);
  const [unlink, setUnlink] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const linked = item.canvas_assignment_id != null && !unlink;

  function start() {
    setTitle(item.title);
    setAsPercent(item.percent != null);
    setEarned(String(item.percent ?? item.earned ?? ""));
    setPossible(String(item.possible ?? ""));
    setSection(componentId);
    setUnlink(false);
    setError(null);
    setEditing(true);
  }

  const save = useMutation({
    mutationFn: () => {
      const num = (v: string) => (v.trim() === "" ? null : Number(v));
      const body: Record<string, unknown> = { title };
      if (section !== componentId) body.component_id = section;
      if (unlink) body.unlink_canvas = true;
      // A Canvas row's score comes from Canvas; send one only once unlinked.
      if (!linked) {
        Object.assign(
          body,
          asPercent
            ? { percent: num(earned), earned: null, possible: null }
            : { earned: num(earned), possible: num(possible), percent: null },
        );
      }
      return api.patch(`/api/grades/items/${item.id}`, body);
    },
    onSuccess: () => {
      setEditing(false);
      onChanged();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not save that score"),
  });

  if (editing) {
    return (
      <form
        className="grade-item-form grade-item-edit"
        onSubmit={(e) => {
          e.preventDefault();
          if (title.trim()) save.mutate();
        }}
      >
        <input
          className="input"
          aria-label="Score name"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          autoFocus
        />
        {linked ? (
          <p className="gen-hint">
            {fmtScore(item)} · from Canvas, refreshed on every Canvas sync.
          </p>
        ) : (
          <div className="grade-item-form-nums">
            <input
              className="input"
              type="number"
              inputMode="decimal"
              step="0.01"
              aria-label={asPercent ? "Percent" : "Points earned"}
              placeholder="not graded"
              value={earned}
              onChange={(e) => setEarned(e.target.value)}
            />
            {asPercent ? (
              <span className="grade-item-form-sep">%</span>
            ) : (
              <>
                <span className="grade-item-form-sep">/</span>
                <input
                  className="input"
                  type="number"
                  inputMode="decimal"
                  step="0.01"
                  min="0.01"
                  aria-label="Points possible"
                  value={possible}
                  onChange={(e) => setPossible(e.target.value)}
                />
              </>
            )}
            <button
              type="button"
              className={`btn grade-item-mode${asPercent ? " active" : ""}`}
              onClick={() => setAsPercent((v) => !v)}
              title="Switch between points and a straight percentage"
            >
              {asPercent ? "percent" : "points"}
            </button>
          </div>
        )}
        <div className="grade-item-edit-row">
          {sections.length > 1 && (
            <label className="grade-item-edit-section">
              Section
              <select
                className="input"
                value={section}
                onChange={(e) => setSection(Number(e.target.value))}
              >
                {sections.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          {item.canvas_assignment_id != null && (
            <label className="grade-item-unlink">
              <input
                type="checkbox"
                checked={unlink}
                onChange={(e) => setUnlink(e.target.checked)}
              />
              Unlink from Canvas (type the score yourself)
            </label>
          )}
        </div>
        {error && <p className="error-text">{error}</p>}
        <div className="grades-add-actions">
          <button className="btn btn-primary" disabled={!title.trim() || save.isPending}>
            Save
          </button>
          <button type="button" className="btn" onClick={() => setEditing(false)}>
            Cancel
          </button>
          <button
            type="button"
            className="btn grade-item-edit-del"
            onClick={() => {
              if (window.confirm(`Remove "${item.title}"?`)) onRemove();
            }}
          >
            <Trash2 size={13} strokeWidth={1.5} /> Remove
          </button>
        </div>
      </form>
    );
  }

  return (
    <div className={`grade-item${item.graded ? "" : " pending"}`}>
      <span className="grade-item-title">{item.title}</span>
      {item.canvas_assignment_id && <span className="badge grade-item-canvas">canvas</span>}
      <GradeValue className="grade-item-score mono">{fmtScore(item)}</GradeValue>
      <button
        className="icon-btn grade-item-edit-btn"
        onClick={start}
        aria-label={`Edit ${item.title}`}
        title="Edit this score"
      >
        <Pencil size={13} strokeWidth={1.5} />
      </button>
    </div>
  );
}
