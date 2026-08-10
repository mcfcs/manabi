import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Layers } from "lucide-react";
import { useState } from "react";

import { api } from "../../lib/api";
import "./review.css";

interface ReviewCard {
  flashcard_id: number;
  front: string;
  back: string;
  module_id: number;
  module_title: string;
  course_code: string | null;
  accent_color: string | null;
}

interface QueueOut {
  due: ReviewCard[];
  due_count: number;
}

const RATINGS = [
  { key: "again", label: "Again", hint: "today", cls: "again" },
  { key: "hard", label: "Hard", hint: "", cls: "hard" },
  { key: "good", label: "Good", hint: "", cls: "good" },
  { key: "easy", label: "Easy", hint: "", cls: "easy" },
];

export function ReviewPage() {
  const queryClient = useQueryClient();
  const [revealed, setRevealed] = useState(false);
  const [done, setDone] = useState(0);

  const queue = useQuery({
    queryKey: ["review-queue"],
    queryFn: () => api.get<QueueOut>("/api/review/queue"),
    staleTime: Infinity, // stable session queue; we splice locally as we rate
  });

  const rate = useMutation({
    mutationFn: (v: { id: number; rating: string }) =>
      api.post<{ due_date: string; interval_days: number }>(
        `/api/review/${v.id}`,
        { rating: v.rating },
      ),
    onSuccess: (_r, v) => {
      setRevealed(false);
      setDone((d) => d + 1);
      queryClient.setQueryData<QueueOut>(["review-queue"], (old) => {
        if (!old) return old;
        const rest = old.due.filter((c) => c.flashcard_id !== v.id);
        // "again" cards return to the end of today's session
        const card = old.due.find((c) => c.flashcard_id === v.id);
        const due = v.rating === "again" && card ? [...rest, card] : rest;
        return { due, due_count: due.length };
      });
      queryClient.invalidateQueries({ queryKey: ["review-due-count"] });
    },
  });

  const card = queue.data?.due[0];
  const remaining = queue.data?.due.length ?? 0;

  return (
    <div className="review-page">
      <header className="review-head">
        <h1>Review</h1>
        <span className="review-progress mono">
          {done} done · {remaining} left
        </span>
      </header>

      {queue.isLoading && <p className="gen-hint">Loading your queue…</p>}

      {!queue.isLoading && !card && (
        <div className="review-done">
          <Layers size={28} strokeWidth={1.25} />
          <h2>{done > 0 ? "Queue cleared." : "Nothing due."}</h2>
          <p>
            {done > 0
              ? `${done} card${done === 1 ? "" : "s"} reviewed — intervals updated.`
              : "Cards become due as their intervals expire. Generate decks in any module to feed the queue."}
          </p>
        </div>
      )}

      {card && (
        <div className="review-card-wrap">
          <span
            className="review-course"
            style={{ color: card.accent_color ?? "var(--accent-blue)" }}
          >
            {card.course_code} · {card.module_title}
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
                >
                  {r.label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
