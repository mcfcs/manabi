import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Layers, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../../lib/api";
import { formatDays } from "./formatDays";
import { LeechesPanel } from "./LeechesPanel";
import { ReviewStats } from "./ReviewStats";
import "./review.css";

interface ReviewCard {
  flashcard_id: number;
  front: string;
  back: string;
  module_id: number;
  module_title: string;
  course_code: string | null;
  accent_color: string | null;
  reps: number;
  lapses: number;
  interval_days: number;
  /** rating → days until the next review if chosen now */
  previews: Record<string, number>;
}

interface QueueOut {
  due: ReviewCard[];
  due_count: number;
  /** never-reviewed cards that are due; only NEW_CARDS_PER_LOAD ship per page */
  new_total: number;
  new_shown: number;
  new_offset: number;
}

const RATINGS = [
  { key: "again", label: "Again", cls: "again", hotkey: "1" },
  { key: "hard", label: "Hard", cls: "hard", hotkey: "2" },
  { key: "good", label: "Good", cls: "good", hotkey: "3" },
  { key: "easy", label: "Easy", cls: "easy", hotkey: "4" },
];

function isTypingTarget(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  return (
    t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable
  );
}

export function ReviewPage() {
  const queryClient = useQueryClient();
  const [revealed, setRevealed] = useState(false);
  const [done, setDone] = useState(0);
  // One-level undo: the card (with its pre-rating previews) we just rated.
  const [lastRated, setLastRated] = useState<ReviewCard | null>(null);
  const [leechNotice, setLeechNotice] = useState<string | null>(null);

  const queue = useQuery({
    queryKey: ["review-queue"],
    queryFn: () => api.get<QueueOut>("/api/review/queue"),
    staleTime: Infinity, // stable session queue; we splice locally as we rate
  });

  const rate = useMutation({
    mutationFn: (v: { id: number; rating: string }) =>
      api.post<{ due_date: string; interval_days: number; leech?: boolean }>(
        `/api/review/${v.id}`,
        { rating: v.rating },
      ),
    onSuccess: (r, v) => {
      setRevealed(false);
      setDone((d) => d + 1);
      const current = queryClient.getQueryData<QueueOut>(["review-queue"]);
      const rated = current?.due.find((c) => c.flashcard_id === v.id) ?? null;
      setLastRated(rated);
      if (r.leech) {
        setLeechNotice(
          "That card hit 8 lapses and was suspended as a leech — it's listed under Leeches below. Press u to undo if that was a slip.",
        );
        queryClient.invalidateQueries({ queryKey: ["review-leeches"] });
      } else {
        setLeechNotice(null);
      }
      queryClient.setQueryData<QueueOut>(["review-queue"], (old) => {
        if (!old) return old;
        const rest = old.due.filter((c) => c.flashcard_id !== v.id);
        // "again" cards return to the end of today's session
        const card = old.due.find((c) => c.flashcard_id === v.id);
        const due = v.rating === "again" && card ? [...rest, card] : rest;
        return { ...old, due, due_count: due.length };
      });
      queryClient.invalidateQueries({ queryKey: ["review-due-count"] });
      queryClient.invalidateQueries({ queryKey: ["review-stats"] });
    },
  });

  const undo = useMutation({
    mutationFn: (card: ReviewCard) =>
      api.post<{ ok: boolean }>(`/api/review/${card.flashcard_id}/undo`, {}),
    onSuccess: (_r, card) => {
      setRevealed(false);
      setDone((d) => Math.max(0, d - 1));
      setLastRated(null);
      setLeechNotice(null);
      queryClient.invalidateQueries({ queryKey: ["review-leeches"] });
      // back to the head of the session, with its pre-rating previews
      queryClient.setQueryData<QueueOut>(["review-queue"], (old) => {
        const rest = (old?.due ?? []).filter((c) => c.flashcard_id !== card.flashcard_id);
        const due = [card, ...rest];
        return {
          new_total: 0,
          new_shown: 0,
          new_offset: 0,
          ...old,
          due,
          due_count: due.length,
        };
      });
      queryClient.invalidateQueries({ queryKey: ["review-due-count"] });
      queryClient.invalidateQueries({ queryKey: ["review-stats"] });
    },
    onError: () => setLastRated(null), // nothing to undo server-side anymore
  });

  // New cards beyond the per-page cap stay on the server until asked for.
  const loadedNew = (queue.data?.new_offset ?? 0) + (queue.data?.new_shown ?? 0);
  const heldBack = Math.max(0, (queue.data?.new_total ?? 0) - loadedNew);
  const loadMore = useMutation({
    mutationFn: () => api.get<QueueOut>(`/api/review/queue?new_offset=${loadedNew}`),
    onSuccess: (page) => {
      queryClient.setQueryData<QueueOut>(["review-queue"], (old) => {
        const seen = new Set((old?.due ?? []).map((c) => c.flashcard_id));
        const fresh = page.due.filter((c) => !seen.has(c.flashcard_id));
        return {
          ...page,
          due: [...(old?.due ?? []), ...fresh],
          due_count: (old?.due.length ?? 0) + fresh.length,
        };
      });
    },
  });

  const card = queue.data?.due[0];
  const remaining = queue.data?.due.length ?? 0;

  // Keyboard: Space/Enter reveals, 1–4 rates, u undoes. Ignored while typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "u" && lastRated && !undo.isPending) {
        e.preventDefault();
        undo.mutate(lastRated);
        return;
      }
      if (!card) return;
      if (!revealed && (e.key === " " || e.key === "Enter")) {
        e.preventDefault();
        setRevealed(true);
        return;
      }
      if (revealed && !rate.isPending) {
        const r = RATINGS.find((x) => x.hotkey === e.key);
        if (r) {
          e.preventDefault();
          rate.mutate({ id: card.flashcard_id, rating: r.key });
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [card, revealed, rate, lastRated, undo]);

  return (
    <div className="review-page">
      <header className="review-head">
        <h1>Review</h1>
        <div className="review-head-right">
          {lastRated && (
            <button
              className="btn review-undo"
              onClick={() => undo.mutate(lastRated)}
              disabled={undo.isPending}
              title="Undo last rating (u)"
            >
              <Undo2 size={13} strokeWidth={1.75} /> Undo
            </button>
          )}
          <span className="review-progress mono">
            {done} done · {remaining} left
            {heldBack > 0 ? ` · ${heldBack} new waiting` : ""}
          </span>
        </div>
      </header>

      <ReviewStats />

      {leechNotice && <p className="review-notice">{leechNotice}</p>}

      {queue.isLoading && <p className="gen-hint">Loading your queue…</p>}

      {!queue.isLoading && !card && (
        <div className="review-done">
          <Layers size={28} strokeWidth={1.25} />
          <h2>{done > 0 ? "Queue cleared." : "Nothing due."}</h2>
          <p>
            {done > 0
              ? `${done} card${done === 1 ? "" : "s"} reviewed — intervals updated.`
              : heldBack > 0
                ? "No reviews are due."
                : "Cards become due as their intervals expire. Generate decks in any module to feed the queue."}
          </p>
          {heldBack > 0 && (
            <>
              <p>
                {heldBack} new card{heldBack === 1 ? " is" : "s are"} held back so a
                fresh deck can't flood one session.
              </p>
              <button
                className="btn btn-primary"
                onClick={() => loadMore.mutate()}
                disabled={loadMore.isPending}
              >
                Load {Math.min(20, heldBack)} more new card{Math.min(20, heldBack) === 1 ? "" : "s"}
              </button>
            </>
          )}
        </div>
      )}

      {card && (
        <div className="review-card-wrap">
          <span
            className="review-course"
            style={{ color: card.accent_color ?? "var(--accent-blue)" }}
          >
            {card.course_code} · {card.module_title}
            {card.reps === 0 ? " · new" : ""}
          </span>
          <button
            className="review-card"
            onClick={() => setRevealed(true)}
            disabled={revealed}
          >
            <p className="review-front">{card.front}</p>
            {revealed ? (
              <>
                <hr className="review-divider" />
                <p className="review-back">{card.back}</p>
              </>
            ) : (
              <span className="review-tap">tap to reveal</span>
            )}
          </button>
          {revealed && (
            <div className="review-ratings">
              {RATINGS.map((r) => (
                <button
                  key={r.key}
                  className={`review-rate ${r.cls}`}
                  onClick={() =>
                    rate.mutate({ id: card.flashcard_id, rating: r.key })
                  }
                  disabled={rate.isPending}
                  title={`${r.label} (${r.hotkey})`}
                >
                  {r.label}
                  <span className="review-rate-hint">
                    {formatDays(card.previews?.[r.key])}
                  </span>
                </button>
              ))}
            </div>
          )}
          <p className="review-kbd-hint">
            {revealed ? (
              <>
                <kbd>1</kbd> again · <kbd>2</kbd> hard · <kbd>3</kbd> good ·{" "}
                <kbd>4</kbd> easy
              </>
            ) : (
              <>
                <kbd>Space</kbd> to reveal
              </>
            )}
            {lastRated && (
              <>
                {" "}
                · <kbd>u</kbd> undo
              </>
            )}
          </p>
        </div>
      )}

      <LeechesPanel />
    </div>
  );
}
