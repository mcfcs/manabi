import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Moon, Pencil, Plus, UserX, Video, X } from "lucide-react";
import { useEffect, useState } from "react";

import {
  api,
  ApiError,
  type CalAbsenceOut,
  type CalendarEventOut,
  type CourseOut,
  type MeetingOut,
} from "../../lib/api";
import { roundupOpen, todayISO } from "../../lib/dates";
import { CourseDialog } from "../courses/CourseDialog";
import {
  absenceFor,
  type DayData,
  eventColor,
  feedColor,
  fmtMin,
  meetingMode,
  modeLabel,
} from "./CalendarPage";

/** Group the day's meetings by their schedule ("Class schedule", "Internship",
 * …) so each renders under its own heading instead of lumping the internship
 * under "Classes". */
function groupBySchedule(meetings: MeetingOut[]): [string, MeetingOut[]][] {
  const map = new Map<string, MeetingOut[]>();
  for (const m of meetings) {
    const key = m.schedule_title || "Schedule";
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(m);
  }
  return [...map.entries()];
}

/** The interactive day content — classes (mode toggles, join links, course
 * edit), tasks (check-off), events (edit), Google events (expandable
 * attendees/RSVP). Used by both the DayPanel side sheet and the full-page
 * Day view so every calendar view has identical capabilities. */
export function DayDetails({
  date,
  data,
  onAddEvent,
  onEditEvent,
}: {
  date: string;
  data: DayData;
  onAddEvent: () => void;
  onEditEvent: (e: CalendarEventOut) => void;
}) {
  const queryClient = useQueryClient();
  const [editCourseId, setEditCourseId] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const courses = useQuery({
    queryKey: ["courses"],
    queryFn: () => api.get<CourseOut[]>("/api/courses"),
    staleTime: 60_000,
  });

  const putMark = useMutation({
    mutationFn: (body: {
      date: string;
      course_id?: number | null;
      block_id?: number | null;
      mode: string | null;
    }) => api.put("/api/calendar/marks", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["calendar"] }),
  });

  const toggleTask = useMutation({
    mutationFn: (t: { id: number; done: boolean }) =>
      api.patch(`/api/tasks/${t.id}`, { done: !t.done }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["calendar"] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
  });

  const wholeDay = data.marks.find(
    (m) => m.course_id === null && m.block_id == null,
  );

  function cycleMode(current: string | undefined): string | null {
    // onsite (none) → async → sync (online) → onsite
    if (!current) return "async";
    if (current === "async") return "sync";
    return null;
  }

  const editCourse =
    editCourseId != null
      ? (courses.data?.find((c) => c.id === editCourseId) ?? null)
      : null;

  const empty =
    !data.meetings.length && !data.tasks.length && !data.events.length && !data.gcal.length;

  return (
    <div className="day-details">
      {empty && <p className="dayview-empty">Nothing on this day.</p>}
      {groupBySchedule(data.meetings).map(([title, mtgs]) => {
        const hasClasses = mtgs.some((m) => m.course_id != null);
        return (
          <section key={title}>
            <h3>{title}</h3>
            {hasClasses && (
              <div className="day-panel-marks">
                <button
                  className={`mark-toggle${wholeDay ? ` ${wholeDay.mode}` : ""}`}
                  onClick={() =>
                    putMark.mutate({
                      date,
                      course_id: null,
                      mode: cycleMode(wholeDay?.mode),
                    })
                  }
                  title="Applies to classes only — cycle: onsite → async → sync (online)"
                >
                  All classes: {wholeDay?.mode ?? "onsite"}
                </button>
              </div>
            )}
            {mtgs.map((m, i) => {
              const specific = data.marks.find(
                (mk) => mk.course_id != null && mk.course_id === m.course_id,
              );
              const mode = meetingMode(m, data);
              const inherited = !specific && !!wholeDay;
              return (
              <div key={i} className="day-row">
                <span
                  className="day-row-dot"
                  style={{ background: m.accent_color ?? "var(--accent-blue)" }}
                />
                <span className="day-row-title">
                  {m.code}
                  <span className="day-row-meta mono">
                    {" "}
                    {fmtMin(m.start_minute)}–{fmtMin(m.end_minute)}
                  </span>
                  <span className="day-row-meta">
                    {" · "}
                    {modeLabel(mode, m.location)}
                  </span>
                </span>
                {m.course_id == null && (
                  <button
                    className={`mark-toggle small ${mode}`}
                    onClick={() =>
                      putMark.mutate({
                        date,
                        block_id: m.block_id,
                        // cycle WFH → RTO → No work → WFH
                        mode:
                          mode === "wfh" ? "rto" : mode === "rto" ? "nowork" : "wfh",
                      })
                    }
                    title="This day: WFH (remote) → RTO (onsite) → No work"
                  >
                    {mode === "rto" ? "RTO" : mode === "nowork" ? "No work" : "WFH"}
                  </button>
                )}
                {mode === "sync" &&
                  (m.meeting_url ? (
                    <a
                      className="btn day-join"
                      href={m.meeting_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <Video size={13} strokeWidth={1.75} /> Join
                    </a>
                  ) : (
                    m.course_id != null && (
                      <button
                        className="btn day-join"
                        onClick={() => setEditCourseId(m.course_id)}
                        title="No meeting link yet — add one"
                      >
                        <Video size={13} strokeWidth={1.75} /> add link
                      </button>
                    )
                  ))}
                {m.course_id != null && (
                  <>
                    <button
                      className={`mark-toggle small${specific ? ` ${specific.mode}` : ""}${inherited ? " inherited" : ""}`}
                      onClick={() =>
                        putMark.mutate({
                          date,
                          course_id: m.course_id,
                          mode: cycleMode(specific?.mode),
                        })
                      }
                      title={
                        inherited
                          ? `Inherited from "All classes" — click to override for this class`
                          : "Cycle: onsite → async → sync (online)"
                      }
                    >
                      {specific?.mode ?? (inherited ? `${wholeDay!.mode}*` : "onsite")}
                    </button>
                    <button
                      className="icon-btn"
                      onClick={() => setEditCourseId(m.course_id)}
                      aria-label="Edit course"
                      title="Edit course (meeting link…)"
                    >
                      <Pencil size={13} strokeWidth={1.5} />
                    </button>
                  </>
                )}
                {m.course_id != null && (
                  <Attendance
                    date={date}
                    courseId={m.course_id}
                    code={m.code}
                    absence={absenceFor(m, data)}
                  />
                )}
              </div>
              );
            })}
          </section>
        );
      })}

      {data.tasks.length > 0 && (
        <section>
          <h3>Tasks due</h3>
          {data.tasks.map((t) => (
            <div key={t.id} className="day-row">
              <input
                type="checkbox"
                checked={t.done}
                onChange={() => toggleTask.mutate(t)}
                aria-label={t.done ? "Mark not done" : "Mark done"}
              />
              <span
                className="day-row-title"
                style={t.done ? { textDecoration: "line-through", color: "var(--ink-faint)" } : undefined}
              >
                {t.title}
                {t.due_minute != null && (
                  <span className="day-row-meta mono"> {fmtMin(t.due_minute)}</span>
                )}
              </span>
              {t.course_code && (
                <span
                  className="day-row-meta"
                  style={{ color: t.accent_color ?? undefined, fontWeight: 600 }}
                >
                  {t.course_code}
                </span>
              )}
            </div>
          ))}
        </section>
      )}

      {data.events.length > 0 && (
        <section>
          <h3>Events</h3>
          {data.events.map((e) => (
            <button
              key={`${e.id}-${e.date}`}
              className="day-row clickable"
              onClick={() => onEditEvent(e)}
            >
              {(e.accent_color || e.schedule_id != null) && (
                <span
                  className="day-row-dot"
                  style={{ background: eventColor(e) }}
                />
              )}
              <span className="day-row-title">
                {e.title}
                {e.start_minute != null && (
                  <span className="day-row-meta mono">
                    {" "}
                    {fmtMin(e.start_minute)}
                    {e.end_minute != null ? `–${fmtMin(e.end_minute)}` : ""}
                  </span>
                )}
                {e.repeat_weekly && <span className="day-row-meta"> · weekly</span>}
                {e.notes && <span className="day-row-meta"> · {e.notes}</span>}
              </span>
            </button>
          ))}
        </section>
      )}

      {data.gcal.length > 0 && (
        <section>
          <h3>Google Calendar</h3>
          {data.gcal.map((g, i) => {
            const key = `g${i}`;
            return (
              <button
                key={key}
                className="day-row clickable"
                onClick={() => setExpanded(expanded === key ? null : key)}
              >
                <span
                  className="day-row-dot"
                  style={{ background: feedColor(g.calendar) }}
                />
                <span className="day-row-title">
                  {g.title}
                  <span className="day-row-meta mono">
                    {g.start_minute != null
                      ? ` ${fmtMin(g.start_minute)}${g.end_minute != null ? `–${fmtMin(g.end_minute)}` : ""}`
                      : " all-day"}
                  </span>
                  {g.my_status && (
                    <span className={`rsvp-badge ${g.my_status}`}>
                      {g.my_status === "needs-action" ? "invited" : g.my_status}
                    </span>
                  )}
                  {expanded === key && (
                    <span className="day-row-detail gcal-detail">
                      {g.calendar && <span>{g.calendar}</span>}
                      {g.location && <span>{g.location}</span>}
                      {g.organizer && <span>Organizer: {g.organizer}</span>}
                      {g.attendees && g.attendees.length > 0 && (
                        <span className="gcal-attendees">
                          {g.attendees.map((at, j) => (
                            <span key={j} className={`gcal-attendee ${at.status}`}>
                              {at.status === "accepted"
                                ? "✓"
                                : at.status === "declined"
                                  ? "✗"
                                  : at.status === "tentative"
                                    ? "~"
                                    : "?"}{" "}
                              {at.name}
                            </span>
                          ))}
                        </span>
                      )}
                      <span className="gcal-rsvp-note">
                        RSVP changes happen in Google Calendar (read-only feed)
                      </span>
                    </span>
                  )}
                </span>
              </button>
            );
          })}
        </section>
      )}

      <Roundups date={date} data={data} />

      <button className="btn day-panel-add" onClick={onAddEvent}>
        <Plus size={15} strokeWidth={1.75} /> Event on this day
      </button>

      {editCourse && (
        <CourseDialog course={editCourse} onClose={() => setEditCourseId(null)} />
      )}
    </div>
  );
}

/** Mark one class meeting absent (1 cut) or late (½), straight into the
 * course's absence log — the same log the course page counts. */
function Attendance({
  date,
  courseId,
  code,
  absence,
}: {
  date: string;
  courseId: number;
  code: string;
  absence: CalAbsenceOut | undefined;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["calendar"] });
    queryClient.invalidateQueries({ queryKey: ["cuts"] });
  };
  const log = useMutation({
    mutationFn: (kind: "cut" | "late") =>
      api.post("/api/cuts", { course_id: courseId, date, kind, reason: reason.trim() || null }),
    onSuccess: () => {
      setOpen(false);
      setReason("");
      refresh();
    },
  });
  const undo = useMutation({
    mutationFn: (id: number) => api.delete(`/api/cuts/${id}`),
    onSuccess: refresh,
  });

  if (absence) {
    return (
      <span className={`absence-badge ${absence.kind}`} title={absence.reason ?? undefined}>
        {absence.kind === "late" ? "Late · ½ cut" : "Absent · 1 cut"}
        <button
          className="absence-undo"
          onClick={() => undo.mutate(absence.id)}
          disabled={undo.isPending}
          aria-label={`Remove the ${absence.kind === "late" ? "late" : "absence"} for ${code}`}
          title="Remove from the absence log"
        >
          <X size={12} strokeWidth={2} />
        </button>
      </span>
    );
  }
  if (!open) {
    return (
      <button
        className="btn absence-open"
        onClick={() => setOpen(true)}
        aria-label={`Absent or late for ${code}?`}
        title={`Log an absence or late for ${code} on this day`}
      >
        <UserX size={13} strokeWidth={1.75} /> <span className="absence-open-label">Absent?</span>
      </button>
    );
  }
  return (
    <div className="absence-picker">
      <button className="btn absence-cut" disabled={log.isPending} onClick={() => log.mutate("cut")}>
        Absent <span className="absence-weight">1 cut</span>
      </button>
      <button className="btn absence-late" disabled={log.isPending} onClick={() => log.mutate("late")}>
        Late <span className="absence-weight">½ cut</span>
      </button>
      <input
        className="input absence-reason"
        placeholder="Reason (optional)"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        aria-label="Reason"
      />
      <button className="icon-btn" onClick={() => setOpen(false)} aria-label="Cancel">
        <X size={14} strokeWidth={1.75} />
      </button>
    </div>
  );
}

/** "What happened in class": one note per class that met, written after
 * the day's classes — from 8 PM today, any time for a past day. */
function Roundups({ date, data }: { date: string; data: DayData }) {
  const classes = [
    ...new Map(
      data.meetings.filter((m) => m.course_id != null).map((m) => [m.course_id!, m]),
    ).values(),
  ];
  if (!classes.length || date > todayISO()) return null;
  const open = roundupOpen(date);
  return (
    <section className="roundup">
      <h3>
        <Moon size={14} strokeWidth={1.75} /> Roundup
      </h3>
      {!open ? (
        <p className="roundup-closed">
          Opens at 8 PM. After the day&apos;s classes, note what happened in each one.
        </p>
      ) : (
        classes.map((m) => (
          <RoundupBox
            key={m.course_id}
            date={date}
            meeting={m}
            saved={data.roundups.find((r) => r.course_id === m.course_id)?.text ?? ""}
          />
        ))
      )}
    </section>
  );
}

function RoundupBox({
  date,
  meeting,
  saved,
}: {
  date: string;
  meeting: MeetingOut;
  saved: string;
}) {
  const queryClient = useQueryClient();
  const [text, setText] = useState(saved);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => setText(saved), [saved]);
  const save = useMutation({
    mutationFn: () => api.put("/api/roundups", { course_id: meeting.course_id, date, text }),
    onSuccess: () => {
      setNote(text.trim() ? "Saved" : "Cleared");
      queryClient.invalidateQueries({ queryKey: ["calendar"] });
      queryClient.invalidateQueries({ queryKey: ["course-roundups", meeting.course_id] });
    },
    onError: (e) => setNote(e instanceof ApiError ? e.message : "Couldn't save"),
  });
  const dirty = text.trim() !== saved.trim();
  return (
    <label className="roundup-box">
      <span className="roundup-head">
        <span
          className="day-row-dot"
          style={{ background: meeting.accent_color ?? "var(--accent-blue)" }}
        />
        <span className="roundup-code">{meeting.code}</span>
        {dirty ? (
          <span className="roundup-note">Unsaved</span>
        ) : (
          note && <span className="roundup-note">{note}</span>
        )}
      </span>
      <textarea
        className="input roundup-text"
        rows={3}
        value={text}
        placeholder="What was covered, announcements, what to review…"
        onChange={(e) => {
          setText(e.target.value);
          setNote(null);
        }}
        onBlur={() => dirty && save.mutate()}
      />
    </label>
  );
}
