import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Flame, Layers, ListTodo } from "lucide-react";

import { api, type TaskOut } from "../../lib/api";

interface StatsOut {
  streak_days: number;
  reviews_total: number;
  quizzes_taken: number;
  avg_quiz_score: number | null;
  checkpoints_answered: number;
  days: { date: string; reviews: number; quizzes: number }[];
}

function StatsStrip() {
  const stats = useQuery({
    queryKey: ["stats"],
    queryFn: () => api.get<StatsOut>("/api/stats"),
    staleTime: 5 * 60_000,
  });
  const reviewDue = useQuery({
    queryKey: ["review-due-count"],
    queryFn: () => api.get<{ count: number }>("/api/review/due-count"),
  });
  const s = stats.data;
  if (!s) return null;
  const max = Math.max(...s.days.map((d) => d.reviews + d.quizzes), 1);
  return (
    <div className="stats-strip">
      <span className="stats-item" title="Consecutive days with study activity">
        <Flame
          size={15}
          strokeWidth={1.75}
          className={s.streak_days > 0 ? "streak-on" : undefined}
        />
        <b>{s.streak_days}</b> day streak
      </span>
      <Link
        to="/review"
        className="stats-item"
        title="Flashcards due for review"
      >
        <Layers size={15} strokeWidth={1.75} />
        <b>{reviewDue.data?.count ?? 0}</b> cards due
      </Link>
      {s.avg_quiz_score != null && (
        <span className="stats-item" title={`${s.quizzes_taken} quizzes taken`}>
          quiz avg <b>{s.avg_quiz_score}%</b>
        </span>
      )}
      <span className="stats-bars" aria-label="Activity, last 14 days">
        {s.days.map((d) => (
          <span
            key={d.date}
            className="stats-bar"
            style={{
              height: `${Math.max(8, ((d.reviews + d.quizzes) / max) * 100)}%`,
              opacity: d.reviews + d.quizzes > 0 ? 1 : 0.25,
            }}
            title={`${d.date}: ${d.reviews} reviews, ${d.quizzes} quizzes`}
          />
        ))}
      </span>
    </div>
  );
}

/** The stats strip and what's due this week. Today's classes, events and day
 * mark live in TodayPanel, which reads them all from one calendar call — this
 * used to re-derive a single "next class" from /api/schedule in JS. */
export function HomeWidgets() {
  const tasks = useQuery({
    queryKey: ["tasks"],
    queryFn: () => api.get<TaskOut[]>("/api/tasks"),
  });

  const today = new Date().toLocaleDateString("sv");
  const weekEnd = new Date(Date.now() + 6 * 86400_000).toLocaleDateString("sv");
  const due = (tasks.data ?? [])
    .filter((t) => !t.done && t.due_date && t.due_date <= weekEnd)
    .sort((a, b) => (a.due_date! < b.due_date! ? -1 : 1))
    .slice(0, 5);

  return (
    <>
      <StatsStrip />
      {due.length > 0 && (
        <div className="home-widgets">
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
                    style={{
                      color: t.course_accent_color ?? "var(--accent-blue)",
                    }}
                  >
                    {t.course_code}
                  </span>
                )}
              </span>
            ))}
          </Link>
        </div>
      )}
    </>
  );
}
