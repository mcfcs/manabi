import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  CloudDownload,
  GraduationCap,
  Loader2,
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
import "./grades.css";

/** The course's syllabus breakdown: weighted sections, their scores, the
 * current standing and what the untouched weight still has to earn. */
export function GradesSection({ courseId }: { courseId: string }) {
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

  const g = grades.data;
  if (!g) return null;

  const empty = g.components.length === 0;
  const warning = weightWarning(g.total_weight);
  const remaining = g.total_weight - g.counted_weight;
  const nextTarget = g.targets[0];

  function submitComponent(e: FormEvent) {
    e.preventDefault();
    if (name.trim() && Number(weight) > 0) addComponent.mutate();
  }

  return (
    <section className="grades-section">
      <div className="module-section-head">
        <h2>
          <GraduationCap size={18} strokeWidth={1.75} /> Grades
        </h2>
        <div className="grades-head-actions">
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
          <button className="btn" onClick={() => setEditingScheme(true)}>
            <SlidersHorizontal size={14} strokeWidth={1.75} />{" "}
            {g.cutoffs ? "Scheme" : "Set scheme"}
          </button>
        </div>
      </div>

      {empty ? (
        <div className="home-empty grades-empty">
          <p>
            Add the sections from this course's syllabus — Participation 10%, Quizzes 30% and so
            on. Only sections with a grade count toward your standing, so an untouched one never
            drags it down.
          </p>
        </div>
      ) : (
        <div className="grades-standing">
          <div className="grades-standing-figure">
            <GradeValue className="grades-percent">{fmtPercent(g.percent)}</GradeValue>
            {g.letter && <GradeValue className="grades-letter">{g.letter}</GradeValue>}
          </div>
          <div className="grades-standing-meta">
            {g.percent == null ? (
              <span>Nothing graded yet.</span>
            ) : (
              <span>
                from {fmtPercent(g.counted_weight)} of the syllabus
                {remaining > 0 ? ` · ${fmtPercent(remaining)} still to come` : " · all graded"}
              </span>
            )}
            {!g.cutoffs && (
              <span className="grades-need-scheme">
                Set the scheme to see a letter.
              </span>
            )}
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
        </div>
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
        <button className="btn grades-add-btn" onClick={() => setAddingComponent(true)}>
          <Plus size={15} strokeWidth={2} /> Add a section
        </button>
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
    </section>
  );
}

function ComponentRow({
  component,
  expanded,
  canLinkCanvas,
  onToggle,
  onLink,
  onRemove,
  onChanged,
}: {
  component: GradeComponentOut;
  expanded: boolean;
  canLinkCanvas: boolean;
  onToggle: () => void;
  onLink: () => void;
  onRemove: () => void;
  onChanged: () => void;
}) {
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
            <ItemRow key={item.id} item={item} onRemove={() => removeItem.mutate(item.id)} />
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
                className="icon-btn danger"
                onClick={onRemove}
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

function ItemRow({ item, onRemove }: { item: GradeItemOut; onRemove: () => void }) {
  return (
    <div className={`grade-item${item.graded ? "" : " pending"}`}>
      <span className="grade-item-title">{item.title}</span>
      {item.canvas_assignment_id && <span className="badge grade-item-canvas">canvas</span>}
      <GradeValue className="grade-item-score mono">{fmtScore(item)}</GradeValue>
      <button
        className="icon-btn danger grade-item-del"
        onClick={onRemove}
        aria-label={`Remove ${item.title}`}
      >
        <Trash2 size={13} strokeWidth={1.5} />
      </button>
    </div>
  );
}
