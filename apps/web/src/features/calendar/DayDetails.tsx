import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Video } from "lucide-react";
import { useState } from "react";

import { api, type CalendarEventOut, type CourseOut } from "../../lib/api";
import { CourseDialog } from "../courses/CourseDialog";
import { type DayData, feedColor, fmtMin, meetingMode } from "./CalendarPage";

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
      course_id: number | null;
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

  const wholeDay = data.marks.find((m) => m.course_id === null);

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
      {data.meetings.length > 0 && (
        <section>
          <h3>Classes</h3>
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
          {data.meetings.map((m, i) => {
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
                    {mode === "sync"
                      ? "online"
                      : mode === "async"
                        ? "async — no meeting"
                        : (m.location ?? "onsite")}
                  </span>
                </span>
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
              </div>
            );
          })}
        </section>
      )}

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
              <span className="day-row-title">
                {e.title}
                {e.start_minute != null && (
                  <span className="day-row-meta mono"> {fmtMin(e.start_minute)}</span>
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

      <button className="btn day-panel-add" onClick={onAddEvent}>
        <Plus size={15} strokeWidth={1.75} /> Event on this day
      </button>

      {editCourse && (
        <CourseDialog course={editCourse} onClose={() => setEditCourseId(null)} />
      )}
    </div>
  );
}
