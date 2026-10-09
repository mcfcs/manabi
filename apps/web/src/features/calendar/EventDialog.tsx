import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Modal } from "../../components/Modal";
import {
  api,
  ApiError,
  type CalendarEventOut,
  type CourseOut,
  type ScheduleOut,
  type SettingsOut,
} from "../../lib/api";
import {
  defaultEventTimes,
  hhmmToMinute as inputToMinute,
  minuteToHHMM as minuteToInput,
  todayISO,
} from "../../lib/dates";

/** A new event's date: the day it was opened from; else today when today
 * is in the month on screen; else that month's first day. */
function initialDate(initial: CalendarEventOut | { date: string } | null, ym: string): string {
  if (initial && "date" in initial && initial.date) return initial.date;
  const today = todayISO();
  return today.startsWith(ym) ? today : `${ym}-01`;
}

export function EventDialog({
  initial,
  onClose,
  ym,
}: {
  initial: CalendarEventOut | { date: string } | null;
  onClose: () => void;
  ym: string;
}) {
  const queryClient = useQueryClient();
  const editing = initial && "id" in initial ? initial : null;

  const [title, setTitle] = useState(editing?.title ?? "");
  const [date, setDate] = useState(() => editing?.date ?? initialDate(initial, ym));
  // Category: "" · "course:<id>" · "sched:<id>" (schedule group, e.g. Internship)
  const [category, setCategory] = useState<string>(
    editing?.schedule_id
      ? `sched:${editing.schedule_id}`
      : editing?.course_id
        ? `course:${editing.course_id}`
        : "",
  );
  // New events start at the next full hour (9:00 on other days), one hour long.
  const [start, setStart] = useState(() =>
    editing ? minuteToInput(editing.start_minute) : minuteToInput(defaultEventTimes(date).start),
  );
  const [end, setEnd] = useState(() =>
    editing ? minuteToInput(editing.end_minute) : minuteToInput(defaultEventTimes(date).end),
  );
  const [weekly, setWeekly] = useState(editing?.repeat_weekly ?? false);
  const [until, setUntil] = useState(editing?.repeat_until ?? "");
  const [notes, setNotes] = useState(editing?.notes ?? "");
  const [error, setError] = useState<string | null>(null);

  const courses = useQuery({
    queryKey: ["courses"],
    queryFn: () => api.get<CourseOut[]>("/api/courses"),
    staleTime: 60_000,
  });
  const schedule = useQuery({
    queryKey: ["schedule"],
    queryFn: () => api.get<ScheduleOut>("/api/schedule"),
    staleTime: 60_000,
  });
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<SettingsOut>("/api/settings"),
    staleTime: 60_000,
  });

  // Moving the start drags the end along, keeping the event's length.
  function changeStart(value: string) {
    const oldStart = inputToMinute(start);
    const oldEnd = inputToMinute(end);
    const next = inputToMinute(value);
    setStart(value);
    if (next != null && oldStart != null && oldEnd != null && oldEnd > oldStart) {
      setEnd(minuteToInput(Math.min(next + (oldEnd - oldStart), 23 * 60 + 59)));
    }
  }
  const startMin = inputToMinute(start);
  const endMin = inputToMinute(end);
  const badRange = startMin != null && endMin != null && endMin <= startMin;

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["calendar"] });

  const save = useMutation({
    mutationFn: () => {
      const isSched = category.startsWith("sched:");
      const isCourse = category.startsWith("course:");
      const id = category.includes(":") ? Number(category.split(":")[1]) : null;
      const body = {
        title: title.trim(),
        notes: notes.trim() || null,
        course_id: isCourse ? id : null,
        schedule_id: isSched ? id : null,
        date,
        start_minute: inputToMinute(start),
        end_minute: inputToMinute(end),
        repeat_weekly: weekly,
        repeat_until: weekly ? until || null : null,
      };
      return editing
        ? api.patch(`/api/calendar/events/${editing.id}`, body)
        : api.post("/api/calendar/events", body);
    },
    onSuccess: () => {
      invalidate();
      onClose();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Save failed"),
  });

  const remove = useMutation({
    mutationFn: () => api.delete(`/api/calendar/events/${editing!.id}`),
    onSuccess: () => {
      invalidate();
      onClose();
    },
  });

  return (
    <Modal title={editing ? "Edit event" : "New event"} onClose={onClose}>
      <div className="modal-form">
        <label className="field-label">
          Title
          <input
            className="input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            autoFocus
          />
        </label>
        <div className="event-form-row">
          <label className="field-label">
            Date
            <input
              type="date"
              className="input"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </label>
          <label className="field-label">
            Category
            <select
              className="input"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              <option value="">—</option>
              <optgroup label="Courses">
                {(courses.data ?? []).map((c) => (
                  <option key={`c${c.id}`} value={`course:${c.id}`}>
                    {c.code}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Schedules">
                {(schedule.data?.schedules ?? []).map((g) => (
                  <option key={`s${g.id}`} value={`sched:${g.id}`}>
                    {g.title}
                  </option>
                ))}
              </optgroup>
            </select>
          </label>
        </div>
        <div className="event-form-row">
          <label className="field-label">
            Start
            <input
              type="time"
              className="input"
              value={start}
              onChange={(e) => changeStart(e.target.value)}
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
        <label className="event-weekly">
          <input
            type="checkbox"
            checked={weekly}
            onChange={(e) => {
              setWeekly(e.target.checked);
              // Weekly until the semester ends unless said otherwise.
              if (e.target.checked && !until && settings.data) setUntil(settings.data.semester_end);
            }}
          />
          Repeats weekly until
          <input
            type="date"
            className="input event-until"
            value={until}
            min={date}
            onChange={(e) => setUntil(e.target.value)}
            disabled={!weekly}
          />
        </label>
        <label className="field-label">
          Notes
          <textarea
            className="input event-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
          />
        </label>

        {badRange && <p className="error-text">The end time must be after the start.</p>}
        {error && <p className="error-text">{error}</p>}

        <div className="modal-actions">
          {editing && (
            <button
              className="btn btn-danger event-delete"
              onClick={() => remove.mutate()}
            >
              Delete
            </button>
          )}
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            disabled={!title.trim() || !date || badRange || save.isPending}
            onClick={() => save.mutate()}
          >
            Save
          </button>
        </div>
      </div>
    </Modal>
  );
}
