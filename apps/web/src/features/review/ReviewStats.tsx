import { useQuery } from "@tanstack/react-query";

import { api } from "../../lib/api";

export interface ReviewStatsOut {
  reviewed_today: number;
  due_now: number;
  in_rotation: number;
  leeches: number;
  /** share of cards reviewed in the last 30 days whose latest rating was good/easy */
  retention_30d: number | null;
  /** cards due per day for the next 7 days; index 0 = today incl. overdue + new */
  forecast: number[];
}

const DAY_LETTERS = ["S", "M", "T", "W", "T", "F", "S"];

function Stat({ value, label, title }: { value: string | number; label: string; title?: string }) {
  return (
    <div className="review-stat" title={title}>
      <span className="review-stat-value">{value}</span>
      <span className="review-stat-label">{label}</span>
    </div>
  );
}

/** KPI row + a 7-day due forecast (single series; today and the peak day are
 * labeled directly, the rest on hover). */
export function ReviewStats() {
  const stats = useQuery({
    queryKey: ["review-stats"],
    queryFn: () => api.get<ReviewStatsOut>("/api/review/stats"),
    staleTime: 60_000,
  });
  const s = stats.data;
  if (!s) return null;

  const max = Math.max(1, ...s.forecast);
  const peak = s.forecast.indexOf(Math.max(...s.forecast));
  const today = new Date();

  return (
    <section className="review-stats" aria-label="Review stats">
      <div className="review-stats-items">
        <Stat value={s.reviewed_today} label="reviewed today" />
        <Stat value={s.due_now} label="due now" />
        <Stat
          value={s.retention_30d == null ? "–" : `${Math.round(s.retention_30d * 100)}%`}
          label="retention · 30d"
          title="Share of cards reviewed in the last 30 days whose latest rating was Good or Easy"
        />
        <Stat value={s.in_rotation} label="in rotation" title="Active cards in decks that feed the queue" />
        {s.leeches > 0 && <Stat value={s.leeches} label="leeches" />}
      </div>
      <div className="review-forecast" role="img" aria-label={`Due over the next 7 days: ${s.forecast.join(", ")}`}>
        {s.forecast.map((n, i) => {
          const d = new Date(today);
          d.setDate(today.getDate() + i);
          const labeled = i === 0 || i === peak;
          return (
            <div
              key={i}
              className="review-forecast-day"
              title={`${i === 0 ? "Today" : d.toLocaleDateString(undefined, { weekday: "short", day: "numeric" })}: ${n} due`}
            >
              <span className="review-forecast-n mono">{labeled ? n : ""}</span>
              <span className="review-forecast-track">
                <span
                  className={`review-forecast-bar${i === 0 ? " today" : ""}`}
                  style={{ height: `${Math.max(n > 0 ? 6 : 2, Math.round((n / max) * 100))}%` }}
                />
              </span>
              <span className="review-forecast-l">{i === 0 ? "now" : DAY_LETTERS[d.getDay()]}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
