import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, ExternalLink, Megaphone } from "lucide-react";
import { useState } from "react";

import { api, type AnnouncementOut } from "../../lib/api";

function relTime(iso: string | null): string {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  const hours = Math.floor(ms / 3_600_000);
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

/** Latest Canvas announcements — all courses (Home) or one (CoursePage).
 * Rows expand in place to the full message (line breaks preserved). */
export function Announcements({
  courseId,
  limit = 5,
}: {
  courseId?: number;
  limit?: number;
}) {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const anns = useQuery({
    queryKey: ["announcements", courseId ?? "all", limit],
    queryFn: () =>
      api.get<AnnouncementOut[]>(
        `/api/canvas/announcements?limit=${limit}${courseId ? `&course_id=${courseId}` : ""}`,
      ),
    staleTime: 5 * 60_000,
    retry: false,
  });

  if (anns.isError || (anns.data && anns.data.length === 0)) return null;

  return (
    <section className="announcements">
      <h2 className="announcements-head">
        <Megaphone size={14} strokeWidth={1.75} /> Announcements
      </h2>
      {anns.isLoading && <div className="ann-skeleton" aria-hidden />}
      {(anns.data ?? []).map((a) => {
        const open = expandedId === a.id;
        return (
          <div key={a.id} className={`ann-row${open ? " open" : ""}`}>
            <button
              className="ann-row-main"
              onClick={() => setExpandedId(open ? null : a.id)}
              aria-expanded={open}
            >
              <span className="ann-chevron">
                {open ? (
                  <ChevronDown size={14} strokeWidth={1.75} />
                ) : (
                  <ChevronRight size={14} strokeWidth={1.75} />
                )}
              </span>
              {!courseId && (
                <span
                  className="ann-course"
                  style={{
                    color: a.accent_color ?? "var(--accent-blue)",
                    background: `color-mix(in srgb, ${a.accent_color ?? "var(--accent-blue)"} 12%, transparent)`,
                  }}
                >
                  {a.course_code ?? "—"}
                </span>
              )}
              <span className="ann-body">
                <span className="ann-title">{a.title}</span>
                {!open && a.preview && a.preview !== "." && (
                  <span className="ann-preview">{a.preview}</span>
                )}
              </span>
              <span className="ann-meta">
                {a.author && <span className="ann-author">{a.author}</span>}
                <span className="ann-time">{relTime(a.posted_at)}</span>
              </span>
            </button>
            {open && (
              <div className="ann-full">
                <p className="ann-message">{a.message || a.preview}</p>
                {a.html_url && (
                  <a
                    className="ann-open-canvas"
                    href={a.html_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open in Canvas <ExternalLink size={11} strokeWidth={1.5} />
                  </a>
                )}
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}
