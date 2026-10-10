import { useQuery } from "@tanstack/react-query";

import { api, type CalendarMonthOut, type MeetingOut } from "../../lib/api";
import { addDaysISO, todayISO } from "../../lib/dates";

/** How far back an absence can be logged — the calendar range API's limit. */
const LOOKBACK_DAYS = 62;

/** The days a class met that can still take an absence or late: today and
 * earlier, not marked async (no meeting), not already logged. Newest first,
 * so [0] is the default — log an absence on a Saturday and it lands on
 * Thursday's class, not on a day the course never met. */
export function loggableDates(
  data: CalendarMonthOut,
  courseId: number,
  today: string,
): string[] {
  const logged = new Set(
    data.absences.filter((a) => a.course_id === courseId).map((a) => a.date),
  );
  const isAsync = (m: MeetingOut) => {
    const marks = data.marks.filter((mk) => mk.date === m.date);
    const own = marks.find((mk) => mk.course_id === courseId);
    const whole = marks.find(
      (mk) => mk.course_id === null && mk.block_id == null,
    );
    return (own?.mode ?? whole?.mode) === "async";
  };
  const dates = data.meetings
    .filter((m) => m.course_id === courseId && m.date <= today && !isAsync(m))
    .map((m) => m.date)
    .filter((d) => !logged.has(d));
  return [...new Set(dates)].sort().reverse();
}

/** loggableDates for one course, fetched over the lookback window. Shares the
 * "calendar" query prefix, so logging anywhere refreshes it. */
export function useLoggableDates(courseId: number | null) {
  const today = todayISO();
  const start = addDaysISO(today, -LOOKBACK_DAYS);
  const range = useQuery({
    queryKey: ["calendar", "attendance", start, today],
    queryFn: () =>
      api.get<CalendarMonthOut>(
        `/api/calendar/range?start=${start}&end=${today}`,
      ),
    enabled: courseId != null,
    staleTime: 60_000,
  });
  const dates =
    range.data && courseId != null
      ? loggableDates(range.data, courseId, today)
      : [];
  return { dates, isLoading: range.isLoading, today };
}

/** "Thu, Oct 8" — or "Today" for today. */
export function classDayLabel(iso: string, today: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const label = new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
  return iso === today ? `Today · ${label}` : label;
}
