import { useQuery } from "@tanstack/react-query";
import { Moon } from "lucide-react";
import { useState } from "react";

import { api, type RoundupOut } from "../../lib/api";

const SHOWN = 5;

function dayLabel(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

/** The course's class log: the evening roundups written on the calendar,
 * newest first. Hidden until there is one. */
export function ClassLog({ courseId }: { courseId: number }) {
  const [all, setAll] = useState(false);
  const log = useQuery({
    queryKey: ["course-roundups", courseId],
    queryFn: () => api.get<RoundupOut[]>(`/api/courses/${courseId}/roundups`),
  });
  const rows = log.data ?? [];
  if (!rows.length) return null;
  const shown = all ? rows : rows.slice(0, SHOWN);
  return (
    <section className="class-log">
      <h2 className="class-log-head">
        <Moon size={15} strokeWidth={1.75} /> Class log
        <span className="class-log-count">{rows.length}</span>
      </h2>
      <ol className="class-log-list">
        {shown.map((r) => (
          <li key={r.id}>
            <time dateTime={r.date}>{dayLabel(r.date)}</time>
            <p>{r.text}</p>
          </li>
        ))}
      </ol>
      {rows.length > SHOWN && (
        <button type="button" className="link-btn" onClick={() => setAll((v) => !v)}>
          {all ? "Show fewer" : `Show all ${rows.length}`}
        </button>
      )}
    </section>
  );
}
