import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { CalendarClock, Layers, Video } from "lucide-react";

import {
  api,
  type CalendarMonthOut,
  type DayMarkOut,
  type GcalEventOut,
  type MeetingOut,
} from "../../lib/api";

/** One row on the timeline, whatever it came from. */
interface Slot {
  key: string;
  kind: "class" | "event" | "gcal";
  label: string;
  start: number | null;
  end: number | null;
  where: string | null;
  color: string | null;
  courseId: number | null;
  joinUrl: string | null;
  group: string | null; // schedule group, e.g. "Internship"
  mark: DayMarkOut | null;
}

const MARK_LABEL: Record<DayMarkOut["mode"], string> = {
  sync: "in person",
  async: "asynchronous",
  rto: "on site",
  wfh: "from home",
  nowork: "no work",
};

function fmt(minute: number): string {
  return `${Math.floor(minute / 60)}:${String(minute % 60).padStart(2, "0")}`;
}

function todayIso(): string {
  return new Date().toLocaleDateString("sv"); // sv gives YYYY-MM-DD in local time
}

/** Whole-day items first, then by start time. */
function bySlot(a: Slot, b: Slot): number {
  if (a.start == null && b.start == null) return 0;
  if (a.start == null) return -1;
  if (b.start == null) return 1;
  return a.start - b.start;
}

function gcalWhere(g: GcalEventOut): string | null {
  return g.location || g.calendar || null;
}

/** A meeting's mark: keyed by course for a class, by block for a labeled block. */
function markFor(m: MeetingOut, marks: DayMarkOut[]): DayMarkOut | null {
  return (
    marks.find((k) => k.block_id === m.block_id) ??
    (m.course_id != null
      ? marks.find((k) => k.course_id === m.course_id)
      : undefined) ??
    null
  );
}

export function TodayPanel() {
  const date = todayIso();
  const day = useQuery({
    // One call: meetings, events, gcal, day marks and tasks. Home used to ask
    // /api/schedule and re-derive "next class" in JS, which meant it could
    // only ever show one meeting and never saw events, gcal or day marks.
    queryKey: ["cal-range", date, date],
    queryFn: () =>
      api.get<CalendarMonthOut>(
        `/api/calendar/range?start=${date}&end=${date}`,
      ),
    staleTime: 60_000,
  });
  const reviewDue = useQuery({
    queryKey: ["review-due-count"],
    queryFn: () => api.get<{ count: number }>("/api/review/due-count"),
  });

  const d = day.data;
  if (!d) return null;

  const dayMark =
    d.marks.find((k) => k.course_id == null && k.block_id == null) ?? null;

  const slots: Slot[] = [
    ...d.meetings.map<Slot>((m) => ({
      key: `m${m.block_id}`,
      kind: "class",
      label: m.code,
      start: m.start_minute,
      end: m.end_minute,
      where: m.location,
      color: m.accent_color,
      courseId: m.course_id,
      joinUrl: m.meeting_url,
      group: m.schedule_title,
      mark: markFor(m, d.marks),
    })),
    ...d.events.map<Slot>((e) => ({
      key: `e${e.id}`,
      kind: "event",
      label: e.title,
      start: e.start_minute,
      end: e.end_minute,
      where: null,
      color: e.accent_color,
      courseId: e.course_id,
      joinUrl: null,
      group: null,
      mark: null,
    })),
    ...d.gcal.map<Slot>((g, i) => ({
      key: `g${i}-${g.title}`,
      kind: "gcal",
      label: g.title,
      start: g.start_minute,
      end: g.end_minute,
      where: gcalWhere(g),
      color: null,
      courseId: null,
      joinUrl: null,
      group: g.calendar,
      mark: null,
    })),
  ].sort(bySlot);

  const now = new Date();
  const nowMin = now.getHours() * 60 + now.getMinutes();
  const nextIdx = slots.findIndex((s) => s.end != null && s.end > nowMin);
  const due = reviewDue.data?.count ?? 0;

  if (slots.length === 0 && !dayMark) return null;

  return (
    <section className="today" aria-label="Today">
      <header className="today-head">
        <CalendarClock size={14} strokeWidth={1.75} />
        <h2>
          {now.toLocaleDateString(undefined, {
            weekday: "long",
            month: "short",
            day: "numeric",
          })}
        </h2>
        {dayMark && (
          <span className="today-mark" title={dayMark.note ?? undefined}>
            {MARK_LABEL[dayMark.mode]}
          </span>
        )}
        <Link to="/calendar" className="today-more">
          Calendar
        </Link>
      </header>

      <ol className="today-list">
        {slots.map((s, i) => {
          const past = s.end != null && s.end <= nowMin;
          const live =
            s.start != null &&
            s.end != null &&
            s.start <= nowMin &&
            s.end > nowMin;
          return (
            <li
              key={s.key}
              className={
                "today-slot" +
                (past ? " past" : "") +
                (live ? " live" : "") +
                (i === nextIdx && !live ? " next" : "")
              }
            >
              <span className="today-time mono">
                {s.start == null ? "all day" : fmt(s.start)}
              </span>
              <span
                className="today-dot"
                style={{ background: s.color ?? "var(--rule)" }}
                aria-hidden
              />
              <span className="today-what">
                <span className="today-label">{s.label}</span>
                <span className="today-sub">
                  {s.end != null && s.start != null
                    ? `until ${fmt(s.end)}`
                    : null}
                  {s.where ? ` · ${s.where}` : ""}
                  {s.mark ? ` · ${MARK_LABEL[s.mark.mode]}` : ""}
                  {s.kind !== "class" && s.group ? ` · ${s.group}` : ""}
                </span>
              </span>
              {live && <span className="today-badge">now</span>}
              {s.joinUrl && !past && (
                <a
                  href={s.joinUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="today-join"
                  aria-label={`Join ${s.label}`}
                  title="Join online meeting"
                >
                  <Video size={13} strokeWidth={1.75} />
                </a>
              )}
              {s.courseId != null && (
                <Link
                  to="/courses/$courseId"
                  params={{ courseId: String(s.courseId) }}
                  className="today-course-link"
                  aria-label={`Open ${s.label}`}
                >
                  open
                </Link>
              )}
            </li>
          );
        })}
      </ol>

      {due > 0 && (
        <Link to="/review" className="today-review">
          <Layers size={14} strokeWidth={1.75} />
          <span>
            <b>{Math.min(due, 20)}</b> card{Math.min(due, 20) === 1 ? "" : "s"}{" "}
            in your next session
          </span>
          <span className="today-review-total">{due} due overall</span>
        </Link>
      )}
    </section>
  );
}
