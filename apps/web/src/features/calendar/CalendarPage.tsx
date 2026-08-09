import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import {
  CalendarPlus,
  ChevronLeft,
  ChevronRight,
  Download,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { useState } from "react";

import {
  api,
  type CalendarEventOut,
  type CalendarMonthOut,
  type DayMarkOut,
} from "../../lib/api";
import { DayPanel } from "./DayPanel";
import { EventDialog } from "./EventDialog";
import "./calendar.css";

export function fmtMin(minute: number): string {
  return `${Math.floor(minute / 60)}:${String(minute % 60).padStart(2, "0")}`;
}

function currentYm(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function clampYm(ym: string, start: string, end: string): string {
  const s = start.slice(0, 7);
  const e = end.slice(0, 7);
  return ym < s ? s : ym > e ? e : ym;
}

function shiftYm(ym: string, delta: number): string {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function monthLabel(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
}

/** All grid cell dates for a Mon-first month view (leading/trailing null). */
function gridDates(ym: string): (string | null)[] {
  const [y, m] = ym.split("-").map(Number);
  const firstDow = (new Date(y, m - 1, 1).getDay() + 6) % 7; // Mon=0
  const daysInMonth = new Date(y, m, 0).getDate();
  const cells: (string | null)[] = Array(firstDow).fill(null);
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push(`${ym}-${String(d).padStart(2, "0")}`);
  }
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

export function CalendarPage() {
  const search = useSearch({ from: "/calendar" });
  const navigate = useNavigate();
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [editingEvent, setEditingEvent] = useState<
    CalendarEventOut | "new" | { date: string } | null
  >(null);
  const queryClient = useQueryClient();

  const ym = search.ym ?? currentYm();
  const month = useQuery({
    queryKey: ["calendar", ym],
    queryFn: () => api.get<CalendarMonthOut>(`/api/calendar/month?ym=${ym}`),
  });

  const refreshGcal = useMutation({
    mutationFn: () =>
      api.post<{ count: number; error: string | null }>("/api/calendar/gcal/refresh"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["calendar"] }),
  });

  const data = month.data;
  const clamped = data ? clampYm(ym, data.semester_start, data.semester_end) : ym;
  const setYm = (next: string) =>
    navigate({ to: "/calendar", search: { ym: next } });

  const byDay = new Map<
    string,
    { meetings: CalendarMonthOut["meetings"]; events: CalendarEventOut[]; gcal: CalendarMonthOut["gcal"]; marks: DayMarkOut[] }
  >();
  if (data) {
    const entry = (d: string) => {
      if (!byDay.has(d)) byDay.set(d, { meetings: [], events: [], gcal: [], marks: [] });
      return byDay.get(d)!;
    };
    for (const m of data.meetings) entry(m.date).meetings.push(m);
    for (const e of data.events) entry(e.date).events.push(e);
    for (const g of data.gcal) entry(g.date).gcal.push(g);
    for (const mk of data.marks) entry(mk.date).marks.push(mk);
  }

  const today = new Date().toLocaleDateString("sv"); // YYYY-MM-DD local

  return (
    <div className="cal-page">
      <header className="cal-head">
        <div className="cal-nav">
          <button
            className="icon-btn"
            onClick={() => setYm(shiftYm(clamped, -1))}
            disabled={!!data && clamped <= data.semester_start.slice(0, 7)}
            aria-label="Previous month"
          >
            <ChevronLeft size={18} strokeWidth={1.5} />
          </button>
          <h1>{monthLabel(clamped)}</h1>
          <button
            className="icon-btn"
            onClick={() => setYm(shiftYm(clamped, 1))}
            disabled={!!data && clamped >= data.semester_end.slice(0, 7)}
            aria-label="Next month"
          >
            <ChevronRight size={18} strokeWidth={1.5} />
          </button>
        </div>
        <div className="cal-actions">
          <button className="btn" onClick={() => setEditingEvent("new")}>
            <CalendarPlus size={15} strokeWidth={1.75} /> Event
          </button>
          {data?.gcal_configured && (
            <button
              className="btn"
              onClick={() => refreshGcal.mutate()}
              disabled={refreshGcal.isPending}
              title="Re-fetch your Google Calendar feed"
            >
              {refreshGcal.isPending ? (
                <Loader2 size={15} className="spin" />
              ) : (
                <RefreshCw size={15} strokeWidth={1.75} />
              )}{" "}
              Google
            </button>
          )}
          <a className="btn" href="/api/calendar/export.ics" download>
            <Download size={15} strokeWidth={1.75} /> .ics
          </a>
        </div>
      </header>

      {refreshGcal.data?.error && (
        <p className="error-text">Google sync: {refreshGcal.data.error}</p>
      )}

      <div className="cal-grid">
        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
          <div key={d} className="cal-dow">
            {d}
          </div>
        ))}
        {gridDates(clamped).map((date, i) => {
          if (!date) return <div key={`x${i}`} className="cal-cell empty" />;
          const day = byDay.get(date);
          const wholeDayMark = day?.marks.find((m) => m.course_id === null);
          const asyncCourseIds = new Set(
            day?.marks.filter((m) => m.mode === "async").map((m) => m.course_id),
          );
          return (
            <button
              key={date}
              className={`cal-cell${date === today ? " today" : ""}`}
              onClick={() => setSelectedDay(date)}
            >
              <span className="cal-daynum">
                {Number(date.slice(8))}
                {wholeDayMark && (
                  <span className={`cal-mark ${wholeDayMark.mode}`}>
                    {wholeDayMark.mode}
                  </span>
                )}
              </span>
              <span className="cal-chips">
                {day?.meetings.map((m, j) => (
                  <span
                    key={`m${j}`}
                    className={`cal-chip meeting${
                      asyncCourseIds.has(m.course_id) ||
                      wholeDayMark?.mode === "async"
                        ? " async"
                        : ""
                    }`}
                    style={{
                      background: `color-mix(in srgb, ${m.accent_color ?? "var(--accent-blue)"} 16%, transparent)`,
                      color: m.accent_color ?? "var(--accent-blue)",
                    }}
                  >
                    {m.code.replace(/\s/g, "")} {fmtMin(m.start_minute)}
                  </span>
                ))}
                {day?.events.map((e) => (
                  <span key={`e${e.id}-${e.date}`} className="cal-chip event">
                    {e.title}
                  </span>
                ))}
                {day?.gcal.map((g, j) => (
                  <span key={`g${j}`} className="cal-chip gcal" title={g.title}>
                    {g.title}
                  </span>
                ))}
              </span>
            </button>
          );
        })}
      </div>

      {selectedDay && data && (
        <DayPanel
          date={selectedDay}
          data={byDay.get(selectedDay) ?? { meetings: [], events: [], gcal: [], marks: [] }}
          onClose={() => setSelectedDay(null)}
          onAddEvent={() => setEditingEvent({ date: selectedDay })}
          onEditEvent={(e) => setEditingEvent(e)}
          ym={clamped}
        />
      )}

      {editingEvent && (
        <EventDialog
          initial={editingEvent === "new" ? null : editingEvent}
          onClose={() => setEditingEvent(null)}
          ym={clamped}
        />
      )}
    </div>
  );
}
