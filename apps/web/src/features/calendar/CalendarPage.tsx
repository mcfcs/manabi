import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import {
  CalendarPlus,
  ChevronLeft,
  ChevronRight,
  Download,
  Loader2,
  RefreshCw,
  Video,
} from "lucide-react";
import { useState } from "react";

import type { CalendarView } from "../../app/router";
import {
  api,
  type CalendarEventOut,
  type CalendarMonthOut,
  type DayMarkOut,
  type GcalEventOut,
  type MeetingOut,
} from "../../lib/api";
import { DayPanel } from "./DayPanel";
import { EventDialog } from "./EventDialog";
import "./calendar.css";

export function fmtMin(minute: number): string {
  return `${Math.floor(minute / 60)}:${String(minute % 60).padStart(2, "0")}`;
}

// ── date helpers (all local, YYYY-MM-DD strings) ─────────────────────────

export function todayStr(): string {
  return new Date().toLocaleDateString("sv");
}

function toDate(d: string): Date {
  return new Date(d + "T00:00:00");
}

function toStr(d: Date): string {
  return d.toLocaleDateString("sv");
}

function addDays(d: string, n: number): string {
  const x = toDate(d);
  x.setDate(x.getDate() + n);
  return toStr(x);
}

function startOfWeek(d: string): string {
  const x = toDate(d);
  return addDays(d, -((x.getDay() + 6) % 7)); // Mon-first
}

function currentYm(): string {
  return todayStr().slice(0, 7);
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

function gridDates(ym: string): (string | null)[] {
  const [y, m] = ym.split("-").map(Number);
  const firstDow = (new Date(y, m - 1, 1).getDay() + 6) % 7;
  const daysInMonth = new Date(y, m, 0).getDate();
  const cells: (string | null)[] = Array(firstDow).fill(null);
  for (let d = 1; d <= daysInMonth; d++)
    cells.push(`${ym}-${String(d).padStart(2, "0")}`);
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

interface DayData {
  meetings: MeetingOut[];
  events: CalendarEventOut[];
  gcal: GcalEventOut[];
  marks: DayMarkOut[];
}

const EMPTY_DAY: DayData = { meetings: [], events: [], gcal: [], marks: [] };

function groupByDay(data: CalendarMonthOut | undefined): Map<string, DayData> {
  const byDay = new Map<string, DayData>();
  if (!data) return byDay;
  const entry = (d: string) => {
    if (!byDay.has(d)) byDay.set(d, { meetings: [], events: [], gcal: [], marks: [] });
    return byDay.get(d)!;
  };
  for (const m of data.meetings) entry(m.date).meetings.push(m);
  for (const e of data.events) entry(e.date).events.push(e);
  for (const g of data.gcal) entry(g.date).gcal.push(g);
  for (const mk of data.marks) entry(mk.date).marks.push(mk);
  return byDay;
}

function useCalendarRange(start: string, end: string) {
  return useQuery({
    queryKey: ["calendar", start, end],
    queryFn: () =>
      api.get<CalendarMonthOut>(`/api/calendar/range?start=${start}&end=${end}`),
  });
}

function meetingMode(
  m: MeetingOut,
  day: DayData,
): "sync" | "async" | "onsite" {
  const specific = day.marks.find(
    (mk) => mk.course_id != null && mk.course_id === m.course_id,
  );
  const whole = day.marks.find((mk) => mk.course_id === null);
  const mode = specific?.mode ?? whole?.mode;
  return mode ?? "onsite"; // neither sync nor async → assume onsite
}

// ── Views ────────────────────────────────────────────────────────────────

function MonthView({
  ym,
  byDay,
  onSelectDay,
}: {
  ym: string;
  byDay: Map<string, DayData>;
  onSelectDay: (d: string) => void;
}) {
  const today = todayStr();
  return (
    <div className="cal-grid">
      {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
        <div key={d} className="cal-dow">
          {d}
        </div>
      ))}
      {gridDates(ym).map((date, i) => {
        if (!date) return <div key={`x${i}`} className="cal-cell empty" />;
        const day = byDay.get(date) ?? EMPTY_DAY;
        const wholeDayMark = day.marks.find((m) => m.course_id === null);
        return (
          <button
            key={date}
            className={`cal-cell${date === today ? " today" : ""}`}
            onClick={() => onSelectDay(date)}
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
              {day.meetings.map((m, j) => {
                const mode = meetingMode(m, day);
                return (
                  <span
                    key={`m${j}`}
                    className={`cal-chip meeting${mode === "async" ? " async" : ""}`}
                    style={{
                      background: `color-mix(in srgb, ${m.accent_color ?? "var(--accent-blue)"} 16%, transparent)`,
                      color: m.accent_color ?? "var(--accent-blue)",
                    }}
                  >
                    {m.code.replace(/\s/g, "")} {fmtMin(m.start_minute)}
                  </span>
                );
              })}
              {day.events.map((e) => (
                <span key={`e${e.id}-${e.date}`} className="cal-chip event">
                  {e.title}
                </span>
              ))}
              {day.gcal.map((g, j) => (
                <span
                  key={`g${j}`}
                  className="cal-chip gcal"
                  title={`${g.title}${g.calendar ? ` (${g.calendar})` : ""}`}
                >
                  {g.title}
                </span>
              ))}
            </span>
          </button>
        );
      })}
    </div>
  );
}

const WEEK_START_MIN = 420; // 07:00
const WEEK_END_MIN = 1320; // 22:00
const WEEK_SPAN = WEEK_END_MIN - WEEK_START_MIN;

function WeekView({
  weekStart,
  byDay,
  onSelectDay,
}: {
  weekStart: string;
  byDay: Map<string, DayData>;
  onSelectDay: (d: string) => void;
}) {
  const today = todayStr();
  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));
  const hours: number[] = [];
  for (let m = 480; m < WEEK_END_MIN; m += 120) hours.push(m);

  return (
    <div className="week-grid">
      <div className="week-gutter">
        {hours.map((m) => (
          <span
            key={m}
            className="timegrid-hour mono"
            style={{ top: `${((m - WEEK_START_MIN) / WEEK_SPAN) * 100}%` }}
          >
            {fmtMin(m)}
          </span>
        ))}
      </div>
      {days.map((date) => {
        const day = byDay.get(date) ?? EMPTY_DAY;
        const allDay = [
          ...day.gcal.filter((g) => g.start_minute == null),
          ...day.events.filter((e) => e.start_minute == null),
        ];
        const wholeDayMark = day.marks.find((m) => m.course_id === null);
        const label = toDate(date).toLocaleDateString(undefined, {
          weekday: "short",
          day: "numeric",
        });
        return (
          <div key={date} className="week-day">
            <button
              className={`week-day-head${date === today ? " today" : ""}`}
              onClick={() => onSelectDay(date)}
            >
              {label}
              {wholeDayMark && (
                <span className={`cal-mark ${wholeDayMark.mode}`}>
                  {wholeDayMark.mode}
                </span>
              )}
            </button>
            <div className="week-allday">
              {allDay.map((item, i) => (
                <span key={i} className="cal-chip gcal" title={item.title}>
                  {item.title}
                </span>
              ))}
            </div>
            <div className="week-day-body">
              {hours.map((m) => (
                <div
                  key={m}
                  className="timegrid-line"
                  style={{ top: `${((m - WEEK_START_MIN) / WEEK_SPAN) * 100}%` }}
                />
              ))}
              {day.meetings.map((m, i) => {
                const mode = meetingMode(m, day);
                const accent = m.accent_color ?? "var(--accent-blue)";
                return (
                  <div
                    key={`m${i}`}
                    className={`week-block${mode === "async" ? " async" : ""}`}
                    style={{
                      top: `${((m.start_minute - WEEK_START_MIN) / WEEK_SPAN) * 100}%`,
                      height: `${((m.end_minute - m.start_minute) / WEEK_SPAN) * 100}%`,
                      borderLeftColor: accent,
                      background: `color-mix(in srgb, ${accent} 13%, var(--surface-raised))`,
                    }}
                    title={`${m.code} ${fmtMin(m.start_minute)}–${fmtMin(m.end_minute)}${
                      m.location ? ` · ${m.location}` : ""
                    } · ${mode}`}
                  >
                    <span style={{ color: accent }}>{m.code.replace(/\s/g, "")}</span>
                    {mode === "sync" && m.meeting_url && (
                      <a
                        href={m.meeting_url}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="sched-block-meet"
                        aria-label="Join online meeting"
                      >
                        <Video size={11} strokeWidth={1.75} />
                      </a>
                    )}
                  </div>
                );
              })}
              {day.events
                .filter((e) => e.start_minute != null)
                .map((e) => (
                  <div
                    key={`e${e.id}-${e.date}`}
                    className="week-block event-block"
                    style={{
                      top: `${((e.start_minute! - WEEK_START_MIN) / WEEK_SPAN) * 100}%`,
                      height: `${(((e.end_minute ?? e.start_minute! + 60) - e.start_minute!) / WEEK_SPAN) * 100}%`,
                    }}
                    title={e.title}
                  >
                    <span>{e.title}</span>
                  </div>
                ))}
              {day.gcal
                .filter((g) => g.start_minute != null)
                .map((g, i) => (
                  <div
                    key={`g${i}`}
                    className="week-block gcal-block"
                    style={{
                      top: `${((g.start_minute! - WEEK_START_MIN) / WEEK_SPAN) * 100}%`,
                      height: `${(((g.end_minute ?? g.start_minute! + 60) - g.start_minute!) / WEEK_SPAN) * 100}%`,
                    }}
                    title={`${g.title}${g.calendar ? ` (${g.calendar})` : ""}`}
                  >
                    <span>{g.title}</span>
                  </div>
                ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function DayView({ date, day }: { date: string; day: DayData }) {
  const items: {
    minute: number | null;
    end: number | null;
    label: string;
    sub: string;
    kind: string;
    accent?: string | null;
    url?: string | null;
  }[] = [
    ...day.meetings.map((m) => {
      const mode = meetingMode(m, day);
      return {
        minute: m.start_minute as number | null,
        end: m.end_minute as number | null,
        label: m.code,
        sub: `${mode}${m.location ? ` · ${m.location}` : ""}`,
        kind: `meeting ${mode}`,
        accent: m.accent_color,
        url: mode === "sync" ? m.meeting_url : null,
      };
    }),
    ...day.events.map((e) => ({
      minute: e.start_minute,
      end: e.end_minute,
      label: e.title,
      sub: e.notes ?? "",
      kind: "event",
      accent: null,
      url: null,
    })),
    ...day.gcal.map((g) => ({
      minute: g.start_minute,
      end: g.end_minute,
      label: g.title,
      sub: [g.calendar, g.location].filter(Boolean).join(" · "),
      kind: "gcal",
      accent: null,
      url: null,
    })),
  ].sort((a, b) => (a.minute ?? -1) - (b.minute ?? -1));

  return (
    <div className="dayview">
      {items.length === 0 && (
        <p className="dayview-empty">Nothing on {date}.</p>
      )}
      {items.map((it, i) => (
        <div key={i} className={`dayview-row ${it.kind}`}>
          <span className="dayview-time mono">
            {it.minute != null
              ? `${fmtMin(it.minute)}${it.end != null ? `–${fmtMin(it.end)}` : ""}`
              : "all-day"}
          </span>
          <span
            className="dayview-dot"
            style={it.accent ? { background: it.accent } : undefined}
          />
          <span className="dayview-label">
            {it.label}
            {it.sub && <span className="dayview-sub"> {it.sub}</span>}
          </span>
          {it.url && (
            <a
              className="btn dayview-join"
              href={it.url}
              target="_blank"
              rel="noreferrer"
            >
              <Video size={14} strokeWidth={1.75} /> Join
            </a>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────

export function CalendarPage() {
  const search = useSearch({ from: "/calendar" });
  const navigate = useNavigate();
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [editingEvent, setEditingEvent] = useState<
    CalendarEventOut | "new" | { date: string } | null
  >(null);
  const queryClient = useQueryClient();

  const view: CalendarView = search.view ?? "month";
  const ym = search.ym ?? currentYm();
  const anchor = search.d ?? todayStr();
  const weekStart = startOfWeek(anchor);

  // range for the active view
  const [start, end] =
    view === "month"
      ? [`${ym}-01`, `${ym}-${String(new Date(Number(ym.slice(0, 4)), Number(ym.slice(5, 7)), 0).getDate()).padStart(2, "0")}`]
      : view === "week"
        ? [weekStart, addDays(weekStart, 6)]
        : [anchor, anchor];

  const range = useCalendarRange(start, end);
  const data = range.data;
  const byDay = groupByDay(data);

  const refreshGcal = useMutation({
    mutationFn: () =>
      api.post<{ count: number; error: string | null }>("/api/calendar/gcal/refresh"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["calendar"] }),
  });

  const clamped = data ? clampYm(ym, data.semester_start, data.semester_end) : ym;

  const go = (next: { view?: CalendarView; ym?: string; d?: string }) =>
    navigate({
      to: "/calendar",
      search: { view, ym: search.ym, d: search.d, ...next },
    });

  function navLabel(): string {
    if (view === "month") return monthLabel(clamped);
    if (view === "week")
      return `${toDate(weekStart).toLocaleDateString(undefined, { month: "short", day: "numeric" })} – ${toDate(addDays(weekStart, 6)).toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
    return toDate(anchor).toLocaleDateString(undefined, {
      weekday: "long",
      month: "long",
      day: "numeric",
    });
  }

  function shift(delta: number) {
    if (view === "month") go({ ym: shiftYm(clamped, delta) });
    else if (view === "week") go({ d: addDays(weekStart, delta * 7) });
    else go({ d: addDays(anchor, delta) });
  }

  return (
    <div className="cal-page">
      <header className="cal-head">
        <div className="cal-nav">
          <button className="icon-btn" onClick={() => shift(-1)} aria-label="Previous">
            <ChevronLeft size={18} strokeWidth={1.5} />
          </button>
          <h1>{navLabel()}</h1>
          <button className="icon-btn" onClick={() => shift(1)} aria-label="Next">
            <ChevronRight size={18} strokeWidth={1.5} />
          </button>
        </div>
        <div className="cal-views">
          {(["month", "week", "day"] as CalendarView[]).map((v) => (
            <button
              key={v}
              className={`cal-view-tab${view === v ? " on" : ""}`}
              onClick={() => go({ view: v, d: v === "month" ? undefined : anchor })}
            >
              {v}
            </button>
          ))}
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
              title="Re-fetch Google Calendar feeds"
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

      {view === "month" && (
        <MonthView ym={clamped} byDay={byDay} onSelectDay={setSelectedDay} />
      )}
      {view === "week" && (
        <WeekView weekStart={weekStart} byDay={byDay} onSelectDay={(d) => go({ view: "day", d })} />
      )}
      {view === "day" && <DayView date={anchor} day={byDay.get(anchor) ?? EMPTY_DAY} />}

      {selectedDay && data && (
        <DayPanel
          date={selectedDay}
          data={byDay.get(selectedDay) ?? EMPTY_DAY}
          onClose={() => setSelectedDay(null)}
          onAddEvent={() => setEditingEvent({ date: selectedDay })}
          onEditEvent={(e) => setEditingEvent(e)}
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
