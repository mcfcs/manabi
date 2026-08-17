import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ExternalLink, Pencil, Plus, Trash2, Video } from "lucide-react";
import { useState } from "react";

import { Modal } from "../../components/Modal";
import {
  api,
  ApiError,
  type CourseOut,
  type ScheduleEntryOut,
  type ScheduleGroupOut,
  type ScheduleOut,
} from "../../lib/api";
import { CourseDialog } from "../courses/CourseDialog";
import "./schedule.css";

const AXIS_START = 450; // 07:30
const AXIS_END = 1230; // 20:30
const AXIS_SPAN = AXIS_END - AXIS_START;
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"];

function fmt(minute: number): string {
  const h = Math.floor(minute / 60);
  const m = minute % 60;
  return `${h}:${String(m).padStart(2, "0")}`;
}

function BlockChip({
  entry,
  editing,
  onDelete,
  onEditCourse,
  axisStart = AXIS_START,
  axisSpan = AXIS_SPAN,
}: {
  entry: ScheduleEntryOut;
  editing: boolean;
  onDelete: () => void;
  onEditCourse: () => void;
  axisStart?: number;
  axisSpan?: number;
}) {
  const navigate = useNavigate();
  const accent = entry.accent_color ?? "var(--accent-blue)";
  const start = entry.start_minute!;
  const end = entry.end_minute!;
  const mins = end - start;
  const top = ((start - axisStart) / axisSpan) * 100;
  const height = ((end - start) / axisSpan) * 100;
  return (
    <div
      className="sched-block"
      style={{
        top: `${top}%`,
        height: `${height}%`,
        borderLeftColor: accent,
        background: `color-mix(in srgb, ${accent} 13%, var(--surface-raised))`,
      }}
      role="button"
      tabIndex={0}
      onClick={() =>
        entry.course_id != null &&
        navigate({
          to: "/courses/$courseId",
          params: { courseId: String(entry.course_id) },
        })
      }
      title={`${entry.name ?? entry.code} · ${fmt(start)}–${fmt(end)}${
        entry.location ? ` · ${entry.location}` : ""
      }${entry.instructor ? ` · ${entry.instructor}` : ""}`}
    >
      <span className="sched-block-line1">
        <span className="sched-block-code" style={{ color: accent }}>
          {entry.code}
        </span>
        {entry.meeting_url && (
          <a
            href={entry.meeting_url}
            target="_blank"
            rel="noreferrer"
            className="sched-block-meet"
            onClick={(e) => e.stopPropagation()}
            title="Join online meeting"
            aria-label="Join online meeting"
          >
            <Video size={12} strokeWidth={1.75} />
          </a>
        )}
      </span>
      <span className="sched-block-time mono">
        {fmt(start)}–{fmt(end)}
        {mins <= 75 && entry.location ? ` · ${entry.location}` : ""}
      </span>
      {mins > 75 && entry.location && (
        <span className="sched-block-room">{entry.location}</span>
      )}
      {mins > 75 && entry.instructor && (
        <span className="sched-block-prof">{entry.instructor}</span>
      )}
      <span className="sched-block-actions">
        {entry.course_id != null && (
          <button
            className="icon-btn sched-block-pencil"
            onClick={(e) => {
              e.stopPropagation();
              onEditCourse();
            }}
            aria-label="Edit course (meeting link…)"
            title="Edit course (meeting link…)"
          >
            <Pencil size={11} strokeWidth={1.5} />
          </button>
        )}
        {editing && (
          <button
            className="icon-btn danger"
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            aria-label="Remove entry"
          >
            <Trash2 size={11} strokeWidth={1.5} />
          </button>
        )}
      </span>
    </div>
  );
}

function EntryDialog({
  schedule,
  onClose,
}: {
  schedule: ScheduleGroupOut;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const courses = useQuery({
    queryKey: ["courses"],
    queryFn: () => api.get<CourseOut[]>("/api/courses"),
    staleTime: 60_000,
  });
  const [courseId, setCourseId] = useState<number | "">("");
  const [label, setLabel] = useState("");
  const [tba, setTba] = useState(false);
  const [days, setDays] = useState<Set<number>>(new Set());
  const [start, setStart] = useState("08:00");
  const [end, setEnd] = useState("09:00");
  const [location, setLocation] = useState("");
  const [error, setError] = useState<string | null>(null);

  const toMin = (v: string) => {
    const [h, m] = v.split(":").map(Number);
    return h * 60 + m;
  };

  const save = useMutation({
    mutationFn: async () => {
      const base = {
        course_id: courseId === "" ? null : courseId,
        label: label.trim() || null,
        location: location.trim() || null,
      };
      if (tba || days.size === 0) {
        await api.post(`/api/schedule/${schedule.id}/entries`, base);
      } else {
        const s = toMin(start);
        let e = toMin(end);
        // An end at/before the start means it runs to (or past) midnight —
        // e.g. an internship 3 PM → 12 AM. Treat 00:00 as end-of-day (1440).
        if (e <= s) e += 24 * 60;
        for (const dow of days) {
          await api.post(`/api/schedule/${schedule.id}/entries`, {
            ...base,
            day_of_week: dow,
            start_minute: s,
            end_minute: e,
          });
        }
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schedule"] });
      queryClient.invalidateQueries({ queryKey: ["calendar"] });
      onClose();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Save failed"),
  });

  return (
    <Modal title={`Add to ${schedule.title}`} onClose={onClose}>
      <div className="modal-form">
        <div className="event-form-row">
          <label className="field-label">
            Course
            <select
              className="input"
              value={courseId}
              onChange={(e) =>
                setCourseId(e.target.value ? Number(e.target.value) : "")
              }
            >
              <option value="">— none —</option>
              {(courses.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code}
                </option>
              ))}
            </select>
          </label>
          <label className="field-label">
            or label
            <input
              className="input"
              placeholder="Internship, Org duty…"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
          </label>
        </div>
        <label className="event-weekly">
          <input
            type="checkbox"
            checked={tba}
            onChange={(e) => setTba(e.target.checked)}
          />
          No fixed time yet (TBA)
        </label>
        {!tba && (
          <>
            <div className="entry-days">
              {DAYS.map((d, i) => (
                <button
                  key={d}
                  type="button"
                  className={`entry-day${days.has(i) ? " on" : ""}`}
                  onClick={() =>
                    setDays((prev) => {
                      const next = new Set(prev);
                      if (next.has(i)) next.delete(i);
                      else next.add(i);
                      return next;
                    })
                  }
                >
                  {d}
                </button>
              ))}
            </div>
            <div className="event-form-row">
              <label className="field-label">
                Start
                <input
                  type="time"
                  className="input"
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                />
              </label>
              <label className="field-label">
                End
                <input
                  type="time"
                  className="input"
                  value={end}
                  onChange={(e) => setEnd(e.target.value)}
                />
              </label>
            </div>
          </>
        )}
        <label className="field-label">
          Location
          <input
            className="input"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
          />
        </label>
        {error && <p className="error-text">{error}</p>}
        <div className="modal-actions">
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            disabled={
              save.isPending ||
              (courseId === "" && !label.trim()) ||
              (!tba && days.size === 0)
            }
            onClick={() => save.mutate()}
          >
            Add
          </button>
        </div>
      </div>
    </Modal>
  );
}

export function SchedulePage() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<number | "all">("all");
  const [editing, setEditing] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [addingTo, setAddingTo] = useState<ScheduleGroupOut | null>(null);
  const [editCourseId, setEditCourseId] = useState<number | null>(null);

  const schedule = useQuery({
    queryKey: ["schedule"],
    queryFn: () => api.get<ScheduleOut>("/api/schedule"),
    staleTime: 60_000,
  });
  const courses = useQuery({
    queryKey: ["courses"],
    queryFn: () => api.get<CourseOut[]>("/api/courses"),
    staleTime: 60_000,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["schedule"] });
    queryClient.invalidateQueries({ queryKey: ["calendar"] });
  };
  const addSchedule = useMutation({
    mutationFn: () => api.post("/api/schedule", { title: newTitle.trim() }),
    onSuccess: () => {
      setNewTitle("");
      invalidate();
    },
  });
  const removeEntry = useMutation({
    mutationFn: (id: number) => api.delete(`/api/schedule/entries/${id}`),
    onSuccess: invalidate,
  });
  const removeSchedule = useMutation({
    mutationFn: (id: number) => api.delete(`/api/schedule/${id}`),
    onSuccess: () => {
      setTab("all");
      invalidate();
    },
  });

  const groups = schedule.data?.schedules ?? [];
  const active = tab === "all" ? null : groups.find((g) => g.id === tab);
  const entries =
    tab === "all" ? groups.flatMap((g) => g.entries) : (active?.entries ?? []);
  const timed = entries.filter((e) => e.day_of_week != null);
  const tba = entries.filter((e) => e.day_of_week == null);

  // Axis fits the entries: default 07:30–20:30, but stretches to hold an early
  // or late block (e.g. an internship running to midnight) instead of clipping.
  const axisStart = Math.min(AXIS_START, ...timed.map((e) => e.start_minute ?? AXIS_START));
  const axisEnd = Math.max(AXIS_END, ...timed.map((e) => e.end_minute ?? AXIS_END));
  const axisSpan = axisEnd - axisStart;

  const hours: number[] = [];
  for (let m = Math.ceil(axisStart / 60) * 60; m < axisEnd; m += 60) hours.push(m);
  const byDay = new Map<number, ScheduleEntryOut[]>();
  for (const b of timed) {
    byDay.set(b.day_of_week!, [...(byDay.get(b.day_of_week!) ?? []), b]);
  }
  const editCourse =
    editCourseId != null
      ? (courses.data?.find((c) => c.id === editCourseId) ?? null)
      : null;

  return (
    <div className="schedule-page">
      <header className="schedule-head">
        <h1>Schedule</h1>
        <span className="schedule-term">1st Sem 2026–27</span>
        <button
          className={`btn schedule-edit${editing ? " on" : ""}`}
          onClick={() => setEditing(!editing)}
        >
          {editing ? "Done" : "Edit"}
        </button>
      </header>

      <div className="schedule-tabs">
        <button
          className={`cal-view-tab${tab === "all" ? " on" : ""}`}
          onClick={() => setTab("all")}
        >
          All
        </button>
        {groups.map((g) => (
          <button
            key={g.id}
            className={`cal-view-tab${tab === g.id ? " on" : ""}`}
            onClick={() => setTab(g.id)}
          >
            {g.title}
          </button>
        ))}
        {editing && (
          <form
            className="schedule-add-row"
            onSubmit={(e) => {
              e.preventDefault();
              if (newTitle.trim()) addSchedule.mutate();
            }}
          >
            <input
              className="input schedule-add-input"
              placeholder="New schedule…"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
            />
            <button className="btn" disabled={!newTitle.trim()}>
              <Plus size={14} strokeWidth={1.75} />
            </button>
          </form>
        )}
      </div>

      {editing && (
        <div className="schedule-edit-actions">
          {tab !== "all" && active ? (
            <>
              <button className="btn" onClick={() => setAddingTo(active)}>
                <Plus size={14} strokeWidth={1.75} /> Entry in {active.title}
              </button>
              <button
                className="btn btn-danger"
                onClick={() => removeSchedule.mutate(active.id)}
              >
                <Trash2 size={14} strokeWidth={1.5} /> Delete {active.title}
              </button>
            </>
          ) : (
            groups.map((g) => (
              <button key={g.id} className="btn" onClick={() => setAddingTo(g)}>
                <Plus size={14} strokeWidth={1.75} /> {g.title}
              </button>
            ))
          )}
        </div>
      )}

      {timed.length > 0 && (
        <>
          <div className="timegrid" role="grid" aria-label="Weekly schedule">
            <div className="timegrid-gutter">
              {hours.map((m) => (
                <span
                  key={m}
                  className="timegrid-hour mono"
                  style={{ top: `${((m - axisStart) / axisSpan) * 100}%` }}
                >
                  {fmt(m)}
                </span>
              ))}
            </div>
            {DAYS.map((label, dow) => (
              <div key={label} className="timegrid-day">
                <div className="timegrid-day-head">{label}</div>
                <div className="timegrid-day-body">
                  {hours.map((m) => (
                    <div
                      key={m}
                      className="timegrid-line"
                      style={{ top: `${((m - axisStart) / axisSpan) * 100}%` }}
                    />
                  ))}
                  {(byDay.get(dow) ?? []).map((b) => (
                    <BlockChip
                      key={b.id}
                      entry={b}
                      editing={editing}
                      onDelete={() => removeEntry.mutate(b.id)}
                      onEditCourse={() => setEditCourseId(b.course_id)}
                      axisStart={axisStart}
                      axisSpan={axisSpan}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="schedule-list">
            {DAYS.map((label, dow) => {
              const blocks = byDay.get(dow) ?? [];
              if (!blocks.length) return null;
              return (
                <section key={label} className="schedule-list-day">
                  <h3>{label}</h3>
                  {blocks.map((b) => (
                    <BlockChip
                      key={b.id}
                      entry={b}
                      editing={editing}
                      onDelete={() => removeEntry.mutate(b.id)}
                      onEditCourse={() => setEditCourseId(b.course_id)}
                    />
                  ))}
                </section>
              );
            })}
          </div>
        </>
      )}

      {tba.length > 0 && (
        <div className="schedule-tba">
          {tba.map((c) => (
            <div key={c.id} className="tba-card">
              <span
                className="tba-dot"
                style={{ background: c.accent_color ?? "var(--accent-blue)" }}
              />
              <div className="tba-body">
                <span className="tba-code">{c.code}</span>
                {c.name && <span className="tba-name">{c.name}</span>}
                <span className="tba-meta">
                  {c.instructor ? `${c.instructor} · ` : ""}TBA
                </span>
              </div>
              {c.course_id != null && (
                <button
                  className="icon-btn"
                  onClick={() => setEditCourseId(c.course_id)}
                  aria-label="Edit course"
                  title="Edit course (meeting link…)"
                >
                  <Pencil size={14} strokeWidth={1.5} />
                </button>
              )}
              {c.meeting_url && (
                <a
                  className="icon-btn"
                  href={c.meeting_url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label="Join online meeting"
                  title="Join online meeting"
                >
                  <Video size={15} strokeWidth={1.5} />
                </a>
              )}
              {c.canvas_url && (
                <a
                  className="icon-btn"
                  href={c.canvas_url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label="Open in Canvas"
                  title="Open in Canvas"
                >
                  <ExternalLink size={15} strokeWidth={1.5} />
                </a>
              )}
              {editing && (
                <button
                  className="icon-btn danger"
                  onClick={() => removeEntry.mutate(c.id)}
                  aria-label="Remove entry"
                >
                  <Trash2 size={14} strokeWidth={1.5} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {addingTo && (
        <EntryDialog schedule={addingTo} onClose={() => setAddingTo(null)} />
      )}
      {editCourse && (
        <CourseDialog course={editCourse} onClose={() => setEditCourseId(null)} />
      )}
    </div>
  );
}
