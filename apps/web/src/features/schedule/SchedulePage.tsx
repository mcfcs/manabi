import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ExternalLink } from "lucide-react";

import { api, type ScheduleBlockOut, type ScheduleOut } from "../../lib/api";
import "./schedule.css";

const AXIS_START = 450; // 07:30
const AXIS_END = 1230; // 20:30
const AXIS_SPAN = AXIS_END - AXIS_START;
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"];

function fmt(minute: number): string {
  const h = Math.floor(minute / 60);
  const m = minute % 60;
  return `${h}:${String(m).padStart(2, "0")}`;
}

function BlockChip({ block }: { block: ScheduleBlockOut }) {
  const navigate = useNavigate();
  const accent = block.accent_color ?? "var(--accent-blue)";
  const top = ((block.start_minute - AXIS_START) / AXIS_SPAN) * 100;
  const height = ((block.end_minute - block.start_minute) / AXIS_SPAN) * 100;
  return (
    <button
      className="sched-block"
      style={{
        top: `${top}%`,
        height: `${height}%`,
        borderLeftColor: accent,
        background: `color-mix(in srgb, ${accent} 13%, var(--surface-raised))`,
      }}
      onClick={() =>
        navigate({
          to: "/courses/$courseId",
          params: { courseId: String(block.course_id) },
        })
      }
      title={`${block.name} · ${fmt(block.start_minute)}–${fmt(block.end_minute)}`}
    >
      <span className="sched-block-code" style={{ color: accent }}>
        {block.code}
      </span>
      <span className="sched-block-time mono">
        {fmt(block.start_minute)}–{fmt(block.end_minute)}
      </span>
      {block.location && <span className="sched-block-room">{block.location}</span>}
    </button>
  );
}

export function SchedulePage() {
  const schedule = useQuery({
    queryKey: ["schedule"],
    queryFn: () => api.get<ScheduleOut>("/api/schedule"),
    staleTime: 5 * 60_000,
  });

  const hours: number[] = [];
  for (let m = 480; m < AXIS_END; m += 60) hours.push(m);

  const byDay = new Map<number, ScheduleBlockOut[]>();
  for (const b of schedule.data?.blocks ?? []) {
    byDay.set(b.day_of_week, [...(byDay.get(b.day_of_week) ?? []), b]);
  }

  return (
    <div className="schedule-page">
      <header className="schedule-head">
        <h1>Schedule</h1>
        <span className="schedule-term">1st Sem 2026–27</span>
      </header>

      <div className="timegrid" role="grid" aria-label="Weekly class schedule">
        <div className="timegrid-gutter">
          {hours.map((m) => (
            <span
              key={m}
              className="timegrid-hour mono"
              style={{ top: `${((m - AXIS_START) / AXIS_SPAN) * 100}%` }}
            >
              {fmt(m)}
            </span>
          ))}
        </div>
        {DAYS.map((label, dow) => (
          <div key={label} className="timegrid-day">
            <div className="timegrid-day-head">{label}</div>
            <div className="timegrid-day-body">
              {hours.map((m) => (
                <div
                  key={m}
                  className="timegrid-line"
                  style={{ top: `${((m - AXIS_START) / AXIS_SPAN) * 100}%` }}
                />
              ))}
              {(byDay.get(dow) ?? []).map((b) => (
                <BlockChip key={b.id} block={b} />
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Mobile: stacked per-day list (grid hidden by CSS) */}
      <div className="schedule-list">
        {DAYS.map((label, dow) => {
          const blocks = byDay.get(dow) ?? [];
          if (!blocks.length) return null;
          return (
            <section key={label} className="schedule-list-day">
              <h2>{label}</h2>
              {blocks.map((b) => (
                <BlockChip key={b.id} block={b} />
              ))}
            </section>
          );
        })}
      </div>

      {(schedule.data?.unscheduled.length ?? 0) > 0 && (
        <aside className="schedule-tba">
          <h2>No fixed schedule</h2>
          {schedule.data!.unscheduled.map((c) => (
            <div key={c.course_id} className="tba-card">
              <span
                className="tba-dot"
                style={{ background: c.accent_color ?? "var(--accent-blue)" }}
              />
              <div className="tba-body">
                <span className="tba-code">{c.code}</span>
                <span className="tba-name">{c.name}</span>
                <span className="tba-meta">
                  {c.instructor ? `${c.instructor} · ` : ""}TBA
                </span>
              </div>
              {c.canvas_url && (
                <a
                  className="icon-btn"
                  href={c.canvas_url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label="Open in Canvas"
                  title="Open in Canvas"
                >
                  <ExternalLink size={15} strokeWidth={1.5} />
                </a>
              )}
            </div>
          ))}
        </aside>
      )}
    </div>
  );
}
