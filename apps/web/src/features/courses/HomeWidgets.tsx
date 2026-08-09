import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { CalendarClock, ListTodo, Video } from "lucide-react";

import {
  api,
  type ScheduleEntryOut,
  type ScheduleOut,
  type TaskOut,
} from "../../lib/api";

function fmt(minute: number): string {
  return `${Math.floor(minute / 60)}:${String(minute % 60).padStart(2, "0")}`;
}

interface NextClass {
  entry: ScheduleEntryOut;
  when: "now" | "today" | "tomorrow" | string; // weekday label otherwise
}

function findNextClass(data: ScheduleOut | undefined): NextClass | null {
  if (!data) return null;
  const timed = data.schedules
    .flatMap((s) => s.entries)
    .filter((e) => e.day_of_week != null && e.start_minute != null);
  if (!timed.length) return null;
  const now = new Date();
  const nowDow = (now.getDay() + 6) % 7;
  const nowMin = now.getHours() * 60 + now.getMinutes();
  for (let offset = 0; offset < 8; offset++) {
    const dow = (nowDow + offset) % 7;
    const candidates = timed
      .filter((e) => e.day_of_week === dow)
      .filter((e) => offset > 0 || e.end_minute! > nowMin)
      .sort((a, b) => a.start_minute! - b.start_minute!);
    if (candidates.length) {
      const entry = candidates[0];
      const when =
        offset === 0
          ? entry.start_minute! <= nowMin
            ? "now"
            : "today"
          : offset === 1
            ? "tomorrow"
            : ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][dow];
      return { entry, when };
    }
  }
  return null;
}

export function HomeWidgets() {
  const schedule = useQuery({
    queryKey: ["schedule"],
    queryFn: () => api.get<ScheduleOut>("/api/schedule"),
    staleTime: 60_000,
  });
  const tasks = useQuery({
    queryKey: ["tasks"],
    queryFn: () => api.get<TaskOut[]>("/api/tasks"),
  });

  const next = findNextClass(schedule.data);
  const today = new Date().toLocaleDateString("sv");
  const weekEnd = new Date(Date.now() + 6 * 86400_000).toLocaleDateString("sv");
  const due = (tasks.data ?? [])
    .filter((t) => !t.done && t.due_date && t.due_date <= weekEnd)
    .sort((a, b) => (a.due_date! < b.due_date! ? -1 : 1))
    .slice(0, 5);

  if (!next && due.length === 0) return null;

  return (
    <div className="home-widgets">
      {next && (
        <Link to="/schedule" className="home-widget">
          <span className="home-widget-head">
            <CalendarClock size={14} strokeWidth={1.75} />
            {next.when === "now" ? "Happening now" : `Next class · ${next.when}`}
          </span>
          <span className="home-widget-main">
            <span
              className="home-widget-dot"
              style={{
                background: next.entry.accent_color ?? "var(--accent-blue)",
              }}
            />
            <b>{next.entry.code}</b>
            <span className="mono home-widget-time">
              {fmt(next.entry.start_minute!)}–{fmt(next.entry.end_minute!)}
            </span>
            {next.entry.location && (
              <span className="home-widget-sub">{next.entry.location}</span>
            )}
            {next.entry.meeting_url && (
              <a
                href={next.entry.meeting_url}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="home-widget-join"
                aria-label="Join online meeting"
              >
                <Video size={13} strokeWidth={1.75} />
              </a>
            )}
          </span>
        </Link>
      )}
      {due.length > 0 && (
        <Link to="/tasks" className="home-widget">
          <span className="home-widget-head">
            <ListTodo size={14} strokeWidth={1.75} />
            Due {due.some((t) => t.due_date! <= today) ? "now" : "this week"}
          </span>
          {due.map((t) => (
            <span key={t.id} className="home-widget-task">
              <span
                className={`home-widget-taskdate mono${
                  t.due_date! <= today ? " urgent" : ""
                }`}
              >
                {t.due_date === today
                  ? "today"
                  : new Date(t.due_date! + "T00:00:00").toLocaleDateString(
                      undefined,
                      { weekday: "short" },
                    )}
              </span>
              <span className="home-widget-tasktitle">{t.title}</span>
              {t.course_code && (
                <span
                  className="home-widget-taskcourse"
                  style={{ color: t.course_accent_color ?? "var(--accent-blue)" }}
                >
                  {t.course_code}
                </span>
              )}
            </span>
          ))}
        </Link>
      )}
    </div>
  );
}
