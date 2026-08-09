import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Video, X } from "lucide-react";

import {
  api,
  type CalendarEventOut,
  type CalendarMonthOut,
  type DayMarkOut,
} from "../../lib/api";
import { fmtMin } from "./CalendarPage";

interface DayData {
  meetings: CalendarMonthOut["meetings"];
  events: CalendarEventOut[];
  gcal: CalendarMonthOut["gcal"];
  marks: DayMarkOut[];
}

export function DayPanel({
  date,
  data,
  onClose,
  onAddEvent,
  onEditEvent,
}: {
  date: string;
  data: DayData;
  onClose: () => void;
  onAddEvent: () => void;
  onEditEvent: (e: CalendarEventOut) => void;
}) {
  const queryClient = useQueryClient();
  const putMark = useMutation({
    mutationFn: (body: {
      date: string;
      course_id: number | null;
      mode: string | null;
    }) => api.put("/api/calendar/marks", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["calendar"] }),
  });

  const wholeDay = data.marks.find((m) => m.course_id === null);
  const markFor = (courseId: number) =>
    data.marks.find((m) => m.course_id === courseId);

  const label = new Date(date + "T00:00:00").toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  function cycleMode(current: string | undefined): string | null {
    // none → async → sync → none (async first: it's the common declaration)
    if (!current) return "async";
    if (current === "async") return "sync";
    return null;
  }

  return (
    <aside className="day-panel">
      <header className="day-panel-head">
        <h2>{label}</h2>
        <button className="icon-btn" onClick={onClose} aria-label="Close">
          <X size={16} strokeWidth={1.5} />
        </button>
      </header>

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
          title="Cycle: none → async → sync"
        >
          Whole day: {wholeDay?.mode ?? "—"}
        </button>
      </div>

      {data.meetings.length > 0 && (
        <section>
          <h3>Classes</h3>
          {data.meetings.map((m, i) => {
            const mark = m.course_id == null ? undefined : markFor(m.course_id);
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
                    {m.location ? ` · ${m.location}` : ""}
                  </span>
                </span>
                {mark?.mode === "sync" && m.meeting_url && (
                  <a
                    className="btn day-join"
                    href={m.meeting_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <Video size={13} strokeWidth={1.75} /> Join
                  </a>
                )}
                {m.course_id != null && (
                  <button
                    className={`mark-toggle small${mark ? ` ${mark.mode}` : ""}`}
                    onClick={() =>
                      putMark.mutate({
                        date,
                        course_id: m.course_id,
                        mode: cycleMode(mark?.mode),
                      })
                    }
                    title="Cycle: onsite → async → sync (online)"
                  >
                    {mark?.mode ?? "onsite"}
                  </button>
                )}
              </div>
            );
          })}
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
              </span>
            </button>
          ))}
        </section>
      )}

      {data.gcal.length > 0 && (
        <section>
          <h3>Google Calendar</h3>
          {data.gcal.map((g, i) => (
            <div key={i} className="day-row gcal-row">
              <span className="day-row-title">
                {g.title}
                <span className="day-row-meta mono">
                  {g.start_minute != null ? ` ${fmtMin(g.start_minute)}` : " all-day"}
                  {g.location ? ` · ${g.location}` : ""}
                </span>
              </span>
            </div>
          ))}
        </section>
      )}

      <button className="btn day-panel-add" onClick={onAddEvent}>
        <Plus size={15} strokeWidth={1.75} /> Event on this day
      </button>
    </aside>
  );
}
