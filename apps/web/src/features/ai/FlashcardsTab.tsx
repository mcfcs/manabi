import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Download,
  Pencil,
  Play,
  RotateCcw,
  Sparkle,
  Trash2,
  X,
} from "lucide-react";
import { type FormEvent, useState } from "react";

import { Modal } from "../../components/Modal";
import { api, type CardOut, type DeckOut, type JobRef } from "../../lib/api";
import {
  AiOfflineBanner,
  CitationPill,
  JobProgress,
  StalenessBadge,
  useAiOnline,
  useGenerationJob,
} from "./common";
import "./flashcards.css";

// ── Review mode ───────────────────────────────────────────────

function ReviewMode({
  cards,
  onExit,
}: {
  cards: CardOut[];
  onExit: () => void;
}) {
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [tally, setTally] = useState({ right: 0, close: 0, wrong: 0 });
  const card = cards[index];
  const done = index >= cards.length;

  function grade(kind: "right" | "close" | "wrong") {
    setTally((t) => ({ ...t, [kind]: t[kind] + 1 }));
    setFlipped(false);
    setIndex((i) => i + 1);
  }

  if (done) {
    return (
      <div className="review-done">
        <h3>Session complete</h3>
        <p>
          <span className="tally right">✓ {tally.right}</span>
          <span className="tally close">~ {tally.close}</span>
          <span className="tally wrong">✗ {tally.wrong}</span>
        </p>
        <div className="review-done-actions">
          <button
            className="btn"
            onClick={() => {
              setIndex(0);
              setTally({ right: 0, close: 0, wrong: 0 });
            }}
          >
            <RotateCcw size={15} strokeWidth={1.75} /> Again
          </button>
          <button className="btn btn-primary" onClick={onExit}>
            Done
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="review">
      <div className="review-meta">
        <span className="mono">
          {index + 1} / {cards.length}
        </span>
        <button className="btn" onClick={onExit}>
          Exit review
        </button>
      </div>
      <button
        className={`review-card${flipped ? " flipped" : ""}`}
        onClick={() => setFlipped((f) => !f)}
      >
        <span className="review-card-inner">
          <span className="review-face front">{card.front}</span>
          <span className="review-face back">{card.back}</span>
        </span>
      </button>
      <p className="review-hint">{flipped ? "" : "tap card to flip"}</p>
      {flipped && (
        <div className="review-grades">
          <button className="btn grade-wrong" onClick={() => grade("wrong")}>
            <X size={16} strokeWidth={2} /> wrong
          </button>
          <button className="btn" onClick={() => grade("close")}>
            ~ close
          </button>
          <button className="btn grade-right" onClick={() => grade("right")}>
            <Check size={16} strokeWidth={2} /> got it
          </button>
        </div>
      )}
      <div className="review-sources">
        {card.citations.map((c) => (
          <CitationPill key={c.id} citation={c} />
        ))}
      </div>
    </div>
  );
}

// ── Card editor ───────────────────────────────────────────────

function CardEditor({
  card,
  moduleId,
  onClose,
}: {
  card: CardOut;
  moduleId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [front, setFront] = useState(card.front);
  const [back, setBack] = useState(card.back);
  const save = useMutation({
    mutationFn: () => api.patch(`/api/flashcards/${card.id}`, { front, back }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["deck", moduleId] });
      onClose();
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }

  return (
    <Modal title="Edit card" onClose={onClose}>
      <form className="modal-form" onSubmit={submit}>
        <div>
          <label className="field-label" htmlFor="card-front">
            Front
          </label>
          <textarea
            id="card-front"
            className="input card-textarea"
            value={front}
            onChange={(e) => setFront(e.target.value)}
            rows={3}
            required
          />
        </div>
        <div>
          <label className="field-label" htmlFor="card-back">
            Back
          </label>
          <textarea
            id="card-back"
            className="input card-textarea"
            value={back}
            onChange={(e) => setBack(e.target.value)}
            rows={4}
            required
          />
        </div>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            Save
          </button>
        </div>
      </form>
    </Modal>
  );
}

// ── Tab ───────────────────────────────────────────────────────

export function FlashcardsTab({ moduleId }: { moduleId: string }) {
  const queryClient = useQueryClient();
  const aiOnline = useAiOnline();
  const [count, setCount] = useState(12);
  const [reviewing, setReviewing] = useState(false);
  const [editing, setEditing] = useState<CardOut | null>(null);

  const deck = useQuery({
    queryKey: ["deck", moduleId],
    queryFn: () => api.get<DeckOut | null>(`/api/modules/${moduleId}/flashcards`),
  });

  const gen = useGenerationJob(moduleId, "generate_flashcards", () => {
    queryClient.invalidateQueries({ queryKey: ["deck", moduleId] });
    queryClient.invalidateQueries({ queryKey: ["deck-versions", moduleId] });
  });

  const [showHistory, setShowHistory] = useState(false);
  const [viewingVersion, setViewingVersion] = useState<number | null>(null);
  const versions = useQuery({
    queryKey: ["deck-versions", moduleId],
    queryFn: () =>
      api.get<
        {
          artifact_id: number;
          generated_at: string;
          item_count: number;
          model_name: string;
        }[]
      >(`/api/modules/${moduleId}/artifacts?type=flashcard_deck`),
    enabled: showHistory,
  });
  const oldDeck = useQuery({
    queryKey: ["artifact", viewingVersion],
    queryFn: () =>
      api.get<DeckOut & { generated_at: string }>(`/api/artifacts/${viewingVersion}`),
    enabled: viewingVersion != null,
  });

  const generate = useMutation({
    mutationFn: () =>
      api.post<JobRef>(`/api/modules/${moduleId}/flashcards/generate`, { count }),
    onSuccess: (ref) => gen.start(ref.job_id),
  });

  const toggleSuspend = useMutation({
    mutationFn: (card: CardOut) =>
      api.patch(`/api/flashcards/${card.id}`, {
        status: card.status === "active" ? "suspended" : "active",
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["deck", moduleId] }),
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/api/flashcards/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["deck", moduleId] }),
  });

  const viewingOld = viewingVersion != null && oldDeck.data != null;
  const d = viewingOld ? oldDeck.data : deck.data;
  const activeCards = d?.cards.filter((c) => c.status === "active") ?? [];

  if (reviewing && activeCards.length > 0) {
    return <ReviewMode cards={activeCards} onExit={() => setReviewing(false)} />;
  }

  return (
    <div className="cards-tab">
      {d && (
        <header className="gen-head">
          <StalenessBadge staleness={d.staleness} />
          <span className="gen-head-meta">
            {d.cards.length} cards · {d.model_name}
          </span>
          <span className="gen-head-spacer" />
          <button
            className={`btn${showHistory ? " active" : ""}`}
            onClick={() => {
              setShowHistory((v) => !v);
              if (showHistory) setViewingVersion(null);
            }}
          >
            History
          </button>
          <button
            className="btn"
            onClick={() => setReviewing(true)}
            disabled={activeCards.length === 0}
          >
            <Play size={15} strokeWidth={1.75} /> Review
          </button>
          <a className="btn" href={`/api/modules/${moduleId}/flashcards/export.apkg`}>
            <Download size={15} strokeWidth={1.75} /> Anki
          </a>
          <button
            className="btn btn-primary"
            onClick={() => generate.mutate()}
            disabled={gen.running || generate.isPending}
          >
            <Sparkle size={15} strokeWidth={1.75} /> Regenerate
          </button>
        </header>
      )}

      {showHistory && versions.data && (
        <div className="version-list">
          {versions.data.map((v) => (
            <button
              key={v.artifact_id}
              className={`version-item${
                (viewingVersion ?? deck.data?.artifact_id) === v.artifact_id
                  ? " current"
                  : ""
              }`}
              onClick={() =>
                setViewingVersion(
                  v.artifact_id === deck.data?.artifact_id ? null : v.artifact_id,
                )
              }
            >
              {new Date(v.generated_at).toLocaleString()} · {v.item_count} cards ·{" "}
              {v.model_name}
              {v.artifact_id === deck.data?.artifact_id && " (latest)"}
            </button>
          ))}
        </div>
      )}

      {viewingOld && (
        <p className="version-banner">
          Viewing an older deck —{" "}
          <button className="link-btn" onClick={() => setViewingVersion(null)}>
            back to latest
          </button>
        </p>
      )}

      {!aiOnline && (gen.running || !d) && <AiOfflineBanner />}
      {gen.running && <JobProgress job={gen.job} />}
      {gen.job?.status === "failed" && (
        <p className="error-text">Generation failed: {gen.job.error}</p>
      )}
      {generate.isError && (
        <p className="error-text">{(generate.error as Error).message}</p>
      )}

      {!d && !gen.running && deck.isSuccess && (
        <div className="gen-empty">
          <p>
            No flashcards yet. Manabi will create source-cited cards from this
            module's materials, prioritizing what your notes emphasize.
          </p>
          <div className="count-picker">
            <select
              className="input quiz-count"
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
            >
              {[12, 20, 30, 40, 60].map((n) => (
                <option key={n} value={n}>
                  {n} cards
                </option>
              ))}
              <option value={0}>All (exhaustive)</option>
            </select>
          </div>
          <p className="gen-hint">
            Key terms and acronyms become exact cards first; the AI adds
            concept, enumeration, and comparison cards — no duplicates.
            {count === 0 &&
              " Exhaustive mode keeps generating until the material runs dry — expect 10–20 minutes."}
          </p>
          <button
            className="btn btn-primary"
            onClick={() => generate.mutate()}
            disabled={generate.isPending}
          >
            <Sparkle size={15} strokeWidth={1.75} /> Generate cards
          </button>
        </div>
      )}

      {d && (
        <div className="card-list">
          {d.cards.map((card) => (
            <div
              key={card.id}
              className={`card-row${card.status === "suspended" ? " suspended" : ""}`}
            >
              <div className="card-row-text">
                <span className="card-front">{card.front}</span>
                <span className="card-back">{card.back}</span>
                <span className="card-cites">
                  {card.citations.map((c) => (
                    <CitationPill key={c.id} citation={c} />
                  ))}
                  {card.edited && <span className="badge stale">edited</span>}
                </span>
              </div>
              {viewingOld ? null : (
              <div className="doc-actions">
                <button
                  className="icon-btn"
                  onClick={() => setEditing(card)}
                  aria-label="Edit card"
                >
                  <Pencil size={15} strokeWidth={1.5} />
                </button>
                <button
                  className="icon-btn"
                  onClick={() => toggleSuspend.mutate(card)}
                  aria-label={card.status === "active" ? "Suspend" : "Unsuspend"}
                  title={card.status === "active" ? "Suspend" : "Unsuspend"}
                >
                  {card.status === "active" ? "⏸" : "▶"}
                </button>
                <button
                  className="icon-btn danger"
                  onClick={() => remove.mutate(card.id)}
                  aria-label="Delete card"
                >
                  <Trash2 size={15} strokeWidth={1.5} />
                </button>
              </div>
              )}
            </div>
          ))}
        </div>
      )}

      {editing && (
        <CardEditor card={editing} moduleId={moduleId} onClose={() => setEditing(null)} />
      )}
    </div>
  );
}
