import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { CalendarClock, ListTodo, UserMinus, Video } from "lucide-react";
import { useState } from "react";

import {
  api,
  type CalendarMonthOut,
  type CourseCutsOut,
  type TaskOut,
} from "../../lib/api";
import { classDayLabel, useLoggableDates } from "../calendar/attendance";

const WEEKDAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function fmt(minute: number): string {
  return `${Math.floor(minute / 60)}:${String(minute % 60).padStart(2, "0")}`;
}

function iso(d: Date): string {
  return d.toLocaleDateString("sv");
}

function dayLabel(dateStr: string, today: string): string {
  if (dateStr === today) return "today";
  const d = new Date(dateStr + "T00:00:00");
  const tomorrow = iso(new Date(Date.now() + 86400_000));
  if (dateStr === tomorrow) return "tomorrow";
  // A weekly class recurs on today's own weekday, so inside a 7-day window a
  // bare "Thu" sits right under "today" and reads as the same day.
  const days = Math.round(
    (d.getTime() - new Date(today + "T00:00:00").getTime()) / 86400_000,
  );
  if (days >= 7) return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return WEEKDAY[(d.getDay() + 6) % 7];
}

/** This course's own meetings, open tasks and attendance — each of which
 * otherwise only existed on an all-courses page somewhere else. Grades stay
 * off the course page by design; see docs/grades.md. */
export function CourseGlance({ courseId }: { courseId: number }) {
  const qc = useQueryClient();
  const [logging, setLogging] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const loggable = useLoggableDates(logging ? courseId : null);
  // Default: the latest class day not yet logged (async days excluded).
  const logDate = picked && loggable.dates.includes(picked) ? picked : loggable.dates[0];
  const today = iso(new Date());
  const end = iso(new Date(Date.now() + 7 * 86400_000));

  const week = useQuery({
    queryKey: ["cal-range", today, end],
    queryFn: () =>
      api.get<CalendarMonthOut>(
        `/api/calendar/range?start=${today}&end=${end}`,
      ),
    staleTime: 60_000,
  });
  const tasks = useQuery({
    queryKey: ["tasks"],
    queryFn: () => api.get<TaskOut[]>("/api/tasks"),
  });
  const cuts = useQuery({
    queryKey: ["cuts"],
    queryFn: () => api.get<CourseCutsOut[]>("/api/cuts"),
  });

  const addCut = useMutation({
    mutationFn: (kind: "cut" | "late") =>
      api.post("/api/cuts", { course_id: courseId, date: logDate, kind }),
    onSuccess: () => {
      setLogging(false);
      setPicked(null);
      qc.invalidateQueries({ queryKey: ["cuts"] });
      // The same log shows on the calendar.
      qc.invalidateQueries({ queryKey: ["calendar"] });
    },
  });

  const meetings = (week.data?.meetings ?? [])
    .filter((m) => m.course_id === courseId)
    .slice(0, 3);
  const due = (tasks.data ?? [])
    .filter((t) => !t.done && t.course_id === courseId)
    .sort((a, b) => ((a.due_date ?? "9") < (b.due_date ?? "9") ? -1 : 1))
    .slice(0, 4);
  const mine = cuts.data?.find((c) => c.course_id === courseId);
  const allowance = mine?.allowance ?? null;
  const used = mine?.total ?? 0;
  const atRisk = allowance != null && used >= allowance;
  const nearLimit = allowance != null && !atRisk && used >= allowance - 1;

  if (week.isLoading && tasks.isLoading && cuts.isLoading) return null;

  return (
    <section className="course-glance" aria-label="This course at a glance">
      <div className="glance-card">
        <h3 className="glance-head">
          <CalendarClock size={13} strokeWidth={1.75} /> Meets
        </h3>
        {meetings.length === 0 ? (
          <p className="glance-empty">Nothing scheduled this week.</p>
        ) : (
          <ul className="glance-list">
            {meetings.map((m) => (
              <li key={`${m.date}-${m.block_id}`}>
                <span className="glance-when mono">
                  {dayLabel(m.date, today)}
                </span>
                <span className="glance-main">
                  {fmt(m.start_minute)}–{fmt(m.end_minute)}
                  {m.location ? ` · ${m.location}` : ""}
                </span>
                {m.meeting_url && (
                  <a
                    href={m.meeting_url}
                    target="_blank"
                    rel="noreferrer"
                    className="glance-join"
                    aria-label="Join online meeting"
                  >
                    <Video size={12} strokeWidth={1.75} />
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="glance-card">
        <h3 className="glance-head">
          <ListTodo size={13} strokeWidth={1.75} /> Due
          <Link to="/tasks" className="glance-more">
            all tasks
          </Link>
        </h3>
        {due.length === 0 ? (
          <p className="glance-empty">Nothing open.</p>
        ) : (
          <ul className="glance-list">
            {due.map((t) => (
              <li key={t.id}>
                <span
                  className={`glance-when mono${
                    t.due_date && t.due_date <= today ? " urgent" : ""
                  }`}
                >
                  {t.due_date ? dayLabel(t.due_date, today) : "—"}
                </span>
                <span className="glance-main">{t.title}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="glance-card">
        <h3 className="glance-head">
          <UserMinus size={13} strokeWidth={1.75} /> Attendance
        </h3>
        <p
          className={`glance-cuts${atRisk ? " at-risk" : nearLimit ? " near" : ""}`}
        >
          <b>{used}</b>
          {allowance != null ? (
            <>
              {" of "}
              {allowance} allowed
            </>
          ) : (
            " used"
          )}
        </p>
        {allowance == null && (
          <p className="glance-empty">
            Set the allowance in the course settings to track this.
          </p>
        )}
        {atRisk && <p className="glance-warn">At the limit.</p>}
        {logging ? (
          loggable.isLoading ? (
            <p className="glance-empty">Finding class days…</p>
          ) : !logDate ? (
            <div className="glance-actions">
              <p className="glance-empty">
                No class day left to log in the last 8 weeks (async days and days already
                logged are skipped).
              </p>
              <button className="btn btn-sm" onClick={() => setLogging(false)}>
                Close
              </button>
            </div>
          ) : (
            <div className="glance-actions">
              <select
                className="input glance-date"
                aria-label="Class day"
                value={logDate}
                onChange={(e) => setPicked(e.target.value)}
              >
                {loggable.dates.map((d) => (
                  <option key={d} value={d}>
                    {classDayLabel(d, loggable.today)}
                  </option>
                ))}
              </select>
              <button
                className="btn btn-sm"
                onClick={() => addCut.mutate("cut")}
                disabled={addCut.isPending}
              >
                Absent
              </button>
              <button
                className="btn btn-sm"
                onClick={() => addCut.mutate("late")}
                disabled={addCut.isPending}
              >
                Late
              </button>
              <button
                className="btn btn-sm"
                onClick={() => {
                  setLogging(false);
                  setPicked(null);
                }}
              >
                Cancel
              </button>
            </div>
          )
        ) : (
          <button
            className="btn btn-sm glance-log"
            onClick={() => setLogging(true)}
          >
            Log absence
          </button>
        )}
      </div>
    </section>
  );
}
