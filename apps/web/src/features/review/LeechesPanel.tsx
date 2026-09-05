import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bug, EyeOff, Pencil, RotateCcw } from "lucide-react";
import { useState } from "react";

import { api } from "../../lib/api";

export interface LeechOut {
  flashcard_id: number;
  front: string;
  back: string;
  module_id: number;
  module_title: string;
  course_code: string | null;
  accent_color: string | null;
  lapses: number;
  reviewed_at: string | null;
}

/** Cards auto-suspended for lapsing too often. Each can be rewritten, started
 * over (back in today's queue), or left suspended and dropped from the list. */
export function LeechesPanel() {
  const queryClient = useQueryClient();
  const leeches = useQuery({
    queryKey: ["review-leeches"],
    queryFn: () => api.get<LeechOut[]>("/api/review/leeches"),
    staleTime: 60_000,
  });
  const [editing, setEditing] = useState<number | null>(null);

  const refresh = (queueToo: boolean) => {
    queryClient.invalidateQueries({ queryKey: ["review-leeches"] });
    queryClient.invalidateQueries({ queryKey: ["review-due-count"] });
    if (queueToo) queryClient.invalidateQueries({ queryKey: ["review-queue"] });
  };
  const reset = useMutation({
    mutationFn: (id: number) => api.post(`/api/review/${id}/leech-reset`, {}),
    onSuccess: () => refresh(true),
  });
  const dismiss = useMutation({
    mutationFn: (id: number) => api.post(`/api/review/${id}/leech-dismiss`, {}),
    onSuccess: () => refresh(false),
  });

  const list = leeches.data ?? [];
  if (list.length === 0) return null;
  const busy = reset.isPending || dismiss.isPending;

  return (
    <section className="review-leeches" aria-label="Leeches">
      <header className="review-leeches-head">
        <h2>
          <Bug size={17} strokeWidth={1.75} /> Leeches
          <span className="badge">{list.length}</span>
        </h2>
        <p>
          Forgotten 8+ times and suspended. Rewrite the card, start it over, or
          leave it out of rotation.
        </p>
      </header>
      {list.map((l) => (
        <LeechRow
          key={l.flashcard_id}
          leech={l}
          editing={editing === l.flashcard_id}
          busy={busy}
          onEdit={() => setEditing(editing === l.flashcard_id ? null : l.flashcard_id)}
          onSaved={() => {
            setEditing(null);
            refresh(false);
          }}
          onReset={() => reset.mutate(l.flashcard_id)}
          onDismiss={() => dismiss.mutate(l.flashcard_id)}
        />
      ))}
    </section>
  );
}

function LeechRow({
  leech,
  editing,
  busy,
  onEdit,
  onSaved,
  onReset,
  onDismiss,
}: {
  leech: LeechOut;
  editing: boolean;
  busy: boolean;
  onEdit: () => void;
  onSaved: () => void;
  onReset: () => void;
  onDismiss: () => void;
}) {
  const [front, setFront] = useState(leech.front);
  const [back, setBack] = useState(leech.back);
  const save = useMutation({
    mutationFn: () => api.patch(`/api/flashcards/${leech.flashcard_id}`, { front, back }),
    onSuccess: onSaved,
  });

  return (
    <article className="leech-row">
      <div className="leech-meta">
        <span
          className="leech-course"
          style={{ color: leech.accent_color ?? "var(--accent-blue)" }}
        >
          {leech.course_code} · {leech.module_title}
        </span>
        <span className="mono">{leech.lapses} lapses</span>
      </div>
      {editing ? (
        <div className="leech-edit">
          <input
            className="input"
            value={front}
            onChange={(e) => setFront(e.target.value)}
            aria-label="Front"
          />
          <textarea
            className="input"
            rows={3}
            value={back}
            onChange={(e) => setBack(e.target.value)}
            aria-label="Back"
          />
          <div className="leech-actions">
            <button
              className="btn btn-primary"
              onClick={() => save.mutate()}
              disabled={save.isPending || !front.trim() || !back.trim()}
            >
              Save rewrite
            </button>
            <button className="btn" onClick={onEdit} disabled={save.isPending}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          <p className="leech-front">{leech.front}</p>
          <p className="leech-back">{leech.back}</p>
          <div className="leech-actions">
            <button className="btn" onClick={onReset} disabled={busy} title="Fresh start: due today">
              <RotateCcw size={13} strokeWidth={1.75} /> Start over
            </button>
            <button className="btn" onClick={onEdit} disabled={busy}>
              <Pencil size={13} strokeWidth={1.75} /> Rewrite
            </button>
            <button
              className="btn"
              onClick={onDismiss}
              disabled={busy}
              title="Stays suspended in its deck; leaves this list"
            >
              <EyeOff size={13} strokeWidth={1.75} /> Keep suspended
            </button>
          </div>
        </>
      )}
    </article>
  );
}
