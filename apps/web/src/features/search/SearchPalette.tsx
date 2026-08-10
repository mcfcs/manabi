import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api } from "../../lib/api";
import "./search.css";

interface SearchHit {
  kind: string;
  title: string;
  snippet: string | null;
  course_id: number | null;
  module_id: number | null;
  document_id: number | null;
  page: number | null;
  accent_color: string | null;
}

const KIND_LABELS: Record<string, string> = {
  course: "Course",
  module: "Module",
  document: "File",
  content: "In text",
  note: "Notes",
  task: "Task",
  event: "Event",
};

export function SearchPalette({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const results = useQuery({
    queryKey: ["search", q],
    queryFn: () =>
      api.get<{ hits: SearchHit[] }>(`/api/search?q=${encodeURIComponent(q)}`),
    enabled: q.trim().length >= 2,
    placeholderData: (prev) => prev,
  });
  const hits = q.trim().length >= 2 ? (results.data?.hits ?? []) : [];

  useEffect(() => {
    inputRef.current?.focus();
  }, []);
  useEffect(() => {
    setSelected(0);
  }, [q]);

  function open(hit: SearchHit) {
    onClose();
    if (hit.kind === "course" && hit.course_id != null) {
      navigate({ to: "/courses/$courseId", params: { courseId: String(hit.course_id) } });
    } else if (hit.kind === "module" || hit.kind === "note") {
      navigate({
        to: "/courses/$courseId/modules/$moduleId",
        params: {
          courseId: String(hit.course_id),
          moduleId: String(hit.module_id),
        },
        search: { tab: hit.kind === "note" ? "notes" : "overview" },
      });
    } else if ((hit.kind === "document" || hit.kind === "content") && hit.document_id != null) {
      navigate({
        to: "/documents/$documentId",
        params: { documentId: String(hit.document_id) },
        search: { page: hit.page ?? 1 },
      });
    } else if (hit.kind === "task") {
      navigate({ to: "/tasks" });
    } else if (hit.kind === "event") {
      navigate({ to: "/calendar", search: {} });
    }
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelected((s) => Math.min(s + 1, hits.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelected((s) => Math.max(s - 1, 0));
    } else if (e.key === "Enter" && hits[selected]) {
      open(hits[selected]);
    } else if (e.key === "Escape") {
      onClose();
    }
  }

  return (
    <div className="palette-overlay" onClick={onClose}>
      <div className="palette" onClick={(e) => e.stopPropagation()}>
        <div className="palette-input-row">
          <Search size={16} strokeWidth={1.5} />
          <input
            ref={inputRef}
            className="palette-input"
            placeholder="Search courses, files, text, notes, tasks…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKey}
          />
          <kbd className="palette-kbd">esc</kbd>
        </div>
        {hits.length > 0 && (
          <div className="palette-results">
            {hits.map((h, i) => (
              <button
                key={`${h.kind}-${i}`}
                className={`palette-hit${i === selected ? " selected" : ""}`}
                onClick={() => open(h)}
                onMouseEnter={() => setSelected(i)}
              >
                <span
                  className="palette-kind"
                  style={h.accent_color ? { color: h.accent_color } : undefined}
                >
                  {KIND_LABELS[h.kind] ?? h.kind}
                </span>
                <span className="palette-body">
                  <span className="palette-title">{h.title}</span>
                  {h.snippet && (
                    <span className="palette-snippet">{h.snippet}</span>
                  )}
                </span>
              </button>
            ))}
          </div>
        )}
        {q.trim().length >= 2 && !results.isLoading && hits.length === 0 && (
          <p className="palette-empty">Nothing found for “{q}”.</p>
        )}
      </div>
    </div>
  );
}
