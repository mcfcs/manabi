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
  type CalTaskOut,
  type DayMarkOut,
  type GcalEventOut,
  type MeetingOut,
} from "../../lib/api";
import { DayDetails } from "./DayDetails";
import { DayPanel } from "./DayPanel";
import { EventDialog } from "./EventDialog";
import "./calendar.css";

export function fmtMin(minute: number): string {
  return `${Math.floor(minute / 60)}:${String(minute % 60).padStart(2, "0")}`;
}

// Stable muted colors for external calendar feeds (distinct from course accents)
const FEED_PALETTE = ["#8A5A00", "#4A6B8A", "#7A4A8A", "#3E7A6E", "#8A3E52"];
const FEED_COLOR_KEY = "manabi-feed-colors";

function feedOverrides(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(FEED_COLOR_KEY) ?? "{}");
  } catch {
    return {};
  }
}

export function setFeedColor(name: string, color: string) {
  const map = feedOverrides();
  map[name] = color;
  localStorage.setItem(FEED_COLOR_KEY, JSON.stringify(map));
}

export function feedColor(name: string | null): string {
  if (!name) return "var(--ink-faint)";
  const override = feedOverrides()[name];
  if (override) return override;
  if (/holiday/i.test(name)) return "#A8552E"; // holidays get a warm fixed tone
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return FEED_PALETTE[h % FEED_PALETTE.length];
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

export interface DayData {
  meetings: MeetingOut[];
  events: CalendarEventOut[];
  gcal: GcalEventOut[];
  marks: DayMarkOut[];
  tasks: CalTaskOut[];
}

export const EMPTY_DAY: DayData = {
  meetings: [],
  events: [],
  gcal: [],
  marks: [],
  tasks: [],
};

function groupByDay(data: CalendarMonthOut | undefined): Map<string, DayData> {
  const byDay = new Map<string, DayData>();
  if (!data) return byDay;
  const entry = (d: string) => {
    if (!byDay.has(d))
      byDay.set(d, { meetings: [], events: [], gcal: [], marks: [], tasks: [] });
    return byDay.get(d)!;
  };
  for (const m of data.meetings) entry(m.date).meetings.push(m);
  for (const e of data.events) entry(e.date).events.push(e);
  for (const g of data.gcal) entry(g.date).gcal.push(g);
  for (const mk of data.marks) entry(mk.date).marks.push(mk);
  for (const t of data.tasks) entry(t.date).tasks.push(t);
  return byDay;
}

/** Mode of one class meeting. Day marks apply ONLY to classes: no mark =
 * onsite, sync = online (Join link), async = no meeting. */
export function meetingMode(
  m: MeetingOut,
  day: DayData,
): "sync" | "async" | "onsite" {
  const specific = day.marks.find(
    (mk) => mk.course_id != null && mk.course_id === m.course_id,
  );
  const whole = day.marks.find((mk) => mk.course_id === null);
  return (specific?.mode ?? whole?.mode ?? "onsite") as "sync" | "async" | "onsite";
}

// ── Filters (persisted) ──────────────────────────────────────────────────

const FILTER_KEY = "manabi-cal-hidden";

function loadHidden(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(FILTER_KEY) ?? "[]"));
  } catch {
    return new Set();
  }
}

function filterDay(day: DayData, hidden: Set<string>): DayData {
  return {
    meetings: hidden.has("classes") ? [] : day.meetings,
    events: hidden.has("events") ? [] : day.events,
    tasks: hidden.has("tasks") ? [] : day.tasks,
    gcal: day.gcal.filter((g) => !hidden.has(`gcal:${g.calendar ?? "Google"}`)),
    marks: day.marks,
  };
}

// ── Chips ────────────────────────────────────────────────────────────────

function TaskChip({ t }: { t: CalTaskOut }) {
  const accent = t.accent_color ?? "var(--ink-soft)";
  return (
    <span
      className={`cal-chip task${t.done ? " done" : ""}`}
      style={{ borderColor: accent, color: accent }}
      title={`Task: ${t.title}${t.course_code ? ` (${t.course_code})` : ""}`}
    >
      ☐ {t.title}
    </span>
  );
}

function MeetingChip({ m, day }: { m: MeetingOut; day: DayData }) {
  const mode = meetingMode(m, day);
  return (
    <span
      className={`cal-chip meeting ${mode}`}
      style={{
        background: `color-mix(in srgb, ${m.accent_color ?? "var(--accent-blue)"} 16%, transparent)`,
        color: m.accent_color ?? "var(--accent-blue)",
      }}
      title={`${m.code} · ${fmtMin(m.start_minute)}–${fmtMin(m.end_minute)} · ${
        mode === "sync" ? "online" : mode === "async" ? "async (no meeting)" : (m.location ?? "onsite")
      }`}
    >
      {m.code.replace(/\s/g, "")}
      <span className="cal-chip-time"> {fmtMin(m.start_minute)}</span>
      {mode === "sync" && <Video size={9} strokeWidth={2} className="cal-chip-video" />}
    </span>
  );
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
              {wholeDayMark && day.meetings.length > 0 && (
                <span
                  className={`cal-mark ${wholeDayMark.mode}`}
                  title={`All classes ${wholeDayMark.mode} this day`}
                >
                  {wholeDayMark.mode}
                </span>
              )}
            </span>
            <span className="cal-chips">
              {day.meetings.map((m, j) => (
                <MeetingChip key={`m${j}`} m={m} day={day} />
              ))}
              {day.tasks.map((t) => (
                <TaskChip key={`t${t.id}`} t={t} />
              ))}
              {day.events.map((e) => (
                <span key={`e${e.id}-${e.date}`} className="cal-chip event">
                  {e.title}
                </span>
              ))}
              {day.gcal.map((g, j) => (
                <span
                  key={`g${j}`}
                  className="cal-chip gcal"
                  style={{
                    background: `color-mix(in srgb, ${feedColor(g.calendar)} 15%, transparent)`,
                    color: feedColor(g.calendar),
                  }}
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

const WEEK_START_MIN = 420; // 07:00 (default window; stretches to fit content)
const WEEK_END_MIN = 1320; // 22:00

/** Assign overlapping spans to side-by-side lanes (Google-Calendar style):
 * transitively-overlapping items form a cluster; each gets the first free lane,
 * and every item in the cluster is widened to 1/lanes so they sit beside each
 * other in a fixed-width column. */
function packLanes<T extends { start: number; end: number }>(
  items: T[],
): { item: T; lane: number; lanes: number }[] {
  const laid = items
    .map((item) => ({ item, lane: 0, lanes: 1 }))
    .sort((a, b) => a.item.start - b.item.start || a.item.end - b.item.end);
  let cluster: (typeof laid)[number][] = [];
  let clusterEnd = -Infinity;
  let colEnds: number[] = [];
  const flush = () => {
    const lanes = colEnds.length || 1;
    for (const c of cluster) c.lanes = lanes;
    cluster = [];
    colEnds = [];
  };
  for (const s of laid) {
    if (s.item.start >= clusterEnd) flush(); // no overlap with cluster → new one
    let lane = colEnds.findIndex((e) => e <= s.item.start);
    if (lane === -1) {
      lane = colEnds.length;
      colEnds.push(s.item.end);
    } else {
      colEnds[lane] = s.item.end;
    }
    s.lane = lane;
    cluster.push(s);
    clusterEnd = Math.max(clusterEnd, s.item.end);
  }
  flush();
  return laid;
}

type WeekTimedItem =
  | { start: number; end: number; kind: "meeting"; m: MeetingOut }
  | { start: number; end: number; kind: "event"; e: CalendarEventOut }
  | { start: number; end: number; kind: "gcal"; g: GcalEventOut };

function WeekView({
  weekStart,
  byDay,
  onSelectDay,
  onOpenDay,
}: {
  weekStart: string;
  byDay: Map<string, DayData>;
  onSelectDay: (d: string) => void;
  onOpenDay: (d: string) => void;
}) {
  const today = todayStr();
  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));

  // Per-day all-day items (top band) + timed items. The visible window
  // stretches to fit anything outside 07:00–22:00 (e.g. an internship running
  // to midnight) so nothing is clipped.
  let winStart = WEEK_START_MIN;
  let winEnd = WEEK_END_MIN;
  const perDay = days.map((date) => {
    const day = byDay.get(date) ?? EMPTY_DAY;
    const allDay = [
      ...day.tasks.map((t) => ({
        title: `☐ ${t.title}`,
        color: t.accent_color ?? "var(--ink-soft)",
      })),
      ...day.gcal
        .filter((g) => g.start_minute == null)
        .map((g) => ({ title: g.title, color: feedColor(g.calendar) })),
      ...day.events
        .filter((e) => e.start_minute == null)
        .map((e) => ({ title: e.title, color: "var(--ink-soft)" })),
    ];
    const timed: WeekTimedItem[] = [
      ...day.meetings.map((m) => ({
        start: m.start_minute,
        end: m.end_minute,
        kind: "meeting" as const,
        m,
      })),
      ...day.events
        .filter((e) => e.start_minute != null)
        .map((e) => ({
          start: e.start_minute!,
          end: e.end_minute ?? e.start_minute! + 60,
          kind: "event" as const,
          e,
        })),
      ...day.gcal
        .filter((g) => g.start_minute != null)
        .map((g) => ({
          start: g.start_minute!,
          end: g.end_minute ?? g.start_minute! + 60,
          kind: "gcal" as const,
          g,
        })),
    ];
    for (const it of timed) {
      winStart = Math.min(winStart, it.start);
      winEnd = Math.max(winEnd, it.end);
    }
    return { date, day, allDay, timed };
  });
  winStart = Math.max(0, winStart);
  winEnd = Math.min(24 * 60, winEnd);
  const winSpan = winEnd - winStart || 1;

  // Uniform all-day band height so every day's time grid starts at the same y
  // (a day with 3 no-time tasks must not push its grid below its neighbours).
  const maxAllDay = Math.max(0, ...perDay.map((d) => d.allDay.length));
  const alldayH = maxAllDay > 0 ? maxAllDay * 20 + 4 : 24;

  const hours: number[] = [];
  for (let m = Math.ceil(winStart / 120) * 120; m < winEnd; m += 120) hours.push(m);

  return (
    <div className="week-scroll">
      <div className="week-grid" style={{ ["--allday-h" as string]: `${alldayH}px` }}>
      <div className="week-gutter">
        {hours.map((m) => (
          <span
            key={m}
            className="timegrid-hour mono"
            style={{ top: `${((m - winStart) / winSpan) * 100}%` }}
          >
            {fmtMin(m)}
          </span>
        ))}
      </div>
      {perDay.map(({ date, day, allDay, timed }) => {
        const wholeDayMark = day.marks.find((m) => m.course_id === null);
        const label = toDate(date).toLocaleDateString(undefined, {
          weekday: "short",
          day: "numeric",
        });
        const laid = packLanes(timed);
        return (
          <div key={date} className="week-day">
            <button
              className={`week-day-head${date === today ? " today" : ""}`}
              onClick={() => onSelectDay(date)}
            >
              {label}
              {wholeDayMark && day.meetings.length > 0 && (
                <span className={`cal-mark ${wholeDayMark.mode}`}>
                  {wholeDayMark.mode}
                </span>
              )}
            </button>
            <div className="week-allday">
              {allDay.map((item, i) => (
                <button
                  key={i}
                  className="cal-chip gcal chip-btn"
                  style={{
                    background: `color-mix(in srgb, ${item.color} 15%, transparent)`,
                    color: item.color,
                  }}
                  title={item.title}
                  onClick={() => onOpenDay(date)}
                >
                  {item.title}
                </button>
              ))}
            </div>
            <div className="week-day-body">
              {hours.map((m) => (
                <div
                  key={m}
                  className="timegrid-line"
                  style={{ top: `${((m - winStart) / winSpan) * 100}%` }}
                />
              ))}
              {laid.map(({ item, lane, lanes }, i) => {
                const top = Math.max(item.start, winStart);
                const bot = Math.min(item.end, winEnd);
                // Fixed-width time column; overlapping items share it in lanes.
                const geo = {
                  top: `${((top - winStart) / winSpan) * 100}%`,
                  height: `${Math.max(1.5, ((bot - top) / winSpan) * 100)}%`,
                  left: `calc(${(lane / lanes) * 100}% + 2px)`,
                  width: `calc(${(1 / lanes) * 100}% - 3px)`,
                  right: "auto" as const,
                };
                if (item.kind === "meeting") {
                  const m = item.m;
                  const mode = meetingMode(m, day);
                  const accent = m.accent_color ?? "var(--accent-blue)";
                  return (
                    <div
                      key={`m${i}`}
                      className={`week-block${mode === "async" ? " async" : ""}`}
                      role="button"
                      tabIndex={0}
                      onClick={() => onOpenDay(date)}
                      style={{
                        ...geo,
                        borderLeftColor: accent,
                        background: `color-mix(in srgb, ${accent} 13%, var(--surface-raised))`,
                      }}
                      title={`${m.code} ${fmtMin(m.start_minute)}–${fmtMin(m.end_minute)} · ${
                        mode === "sync" ? "online" : mode === "async" ? "async" : (m.location ?? "onsite")
                      }`}
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
                }
                if (item.kind === "event") {
                  const e = item.e;
                  return (
                    <div
                      key={`e${e.id}-${date}`}
                      className="week-block event-block"
                      role="button"
                      tabIndex={0}
                      onClick={() => onOpenDay(date)}
                      style={geo}
                      title={e.title}
                    >
                      <span>{e.title}</span>
                    </div>
                  );
                }
                const g = item.g;
                return (
                  <div
                    key={`g${i}`}
                    className="week-block gcal-block"
                    role="button"
                    tabIndex={0}
                    onClick={() => onOpenDay(date)}
                    style={{
                      ...geo,
                      borderLeftColor: feedColor(g.calendar),
                      background: `color-mix(in srgb, ${feedColor(g.calendar)} 13%, var(--surface-raised))`,
                      color: feedColor(g.calendar),
                    }}
                    title={`${g.title}${g.calendar ? ` (${g.calendar})` : ""}`}
                  >
                    <span>{g.title}</span>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
      </div>
    </div>
  );
}

function DayView({
  date,
  day,
  onAddEvent,
  onEditEvent,
}: {
  date: string;
  day: DayData;
  onAddEvent: () => void;
  onEditEvent: (e: CalendarEventOut) => void;
}) {
  return (
    <div className="dayview">
      <DayDetails
        date={date}
        data={day}
        onAddEvent={onAddEvent}
        onEditEvent={onEditEvent}
      />
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
  const [hidden, setHidden] = useState<Set<string>>(loadHidden);
  const [, setColorTick] = useState(0); // re-render after a feed color change
  const queryClient = useQueryClient();

  const view: CalendarView = search.view ?? "month";
  const ym = search.ym ?? currentYm();
  const anchor = search.d ?? todayStr();
  const weekStart = startOfWeek(anchor);

  const [start, end] =
    view === "month"
      ? [
          `${ym}-01`,
          `${ym}-${String(new Date(Number(ym.slice(0, 4)), Number(ym.slice(5, 7)), 0).getDate()).padStart(2, "0")}`,
        ]
      : view === "week"
        ? [weekStart, addDays(weekStart, 6)]
        : [anchor, anchor];

  const range = useQuery({
    queryKey: ["calendar", start, end],
    queryFn: () =>
      api.get<CalendarMonthOut>(`/api/calendar/range?start=${start}&end=${end}`),
  });
  const data = range.data;

  const rawByDay = groupByDay(data);
  const byDay = new Map(
    [...rawByDay.entries()].map(([d, day]) => [d, filterDay(day, hidden)]),
  );
  const feedNames = [
    ...new Set((data?.gcal ?? []).map((g) => g.calendar ?? "Google")),
  ].sort();

  const toggleFilter = (key: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      localStorage.setItem(FILTER_KEY, JSON.stringify([...next]));
      return next;
    });

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

  const filters: { key: string; label: string; color?: string }[] = [
    { key: "classes", label: "Classes" },
    { key: "events", label: "Events" },
    { key: "tasks", label: "Tasks" },
    ...feedNames.map((n) => ({
      key: `gcal:${n}`,
      label: n,
      color: feedColor(n),
    })),
  ];

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

      <div className="cal-filters">
        {filters.map((f) => (
          <span key={f.key} className="cal-filter-wrap">
            <button
              className={`cal-filter${hidden.has(f.key) ? " off" : ""}`}
              style={
                f.color && !hidden.has(f.key)
                  ? { borderColor: f.color, color: f.color }
                  : undefined
              }
              onClick={() => toggleFilter(f.key)}
            >
              {f.label}
            </button>
            {f.color && (
              <input
                type="color"
                className="cal-filter-color"
                value={f.color.startsWith("#") ? f.color : "#888888"}
                onChange={(e) => {
                  setFeedColor(f.label, e.target.value);
                  setColorTick((t) => t + 1);
                }}
                title={`Pick a color for ${f.label}`}
                aria-label={`Color for ${f.label}`}
              />
            )}
          </span>
        ))}
      </div>

      {refreshGcal.data?.error && (
        <p className="error-text">Google sync: {refreshGcal.data.error}</p>
      )}

      {view === "month" && (
        <MonthView ym={clamped} byDay={byDay} onSelectDay={setSelectedDay} />
      )}
      {view === "week" && (
        <WeekView
          weekStart={weekStart}
          byDay={byDay}
          onSelectDay={(d) => go({ view: "day", d })}
          onOpenDay={setSelectedDay}
        />
      )}
      {view === "day" && (
        <DayView
          date={anchor}
          day={byDay.get(anchor) ?? EMPTY_DAY}
          onAddEvent={() => setEditingEvent({ date: anchor })}
          onEditEvent={(e) => setEditingEvent(e)}
        />
      )}

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
