import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import {
  ArrowLeft,
  BookMarked,
  Check,
  Download,
  Pencil,
  Play,
  Plus,
  RotateCcw,
  Sparkle,
  Trash2,
  X,
} from "lucide-react";
import { type FormEvent, useState } from "react";

import { Modal } from "../../components/Modal";
import {
  api,
  type CardOut,
  type DeckListItem,
  type DeckOut,
  type GenerationMode,
  type JobRef,
} from "../../lib/api";
import {
  AiOfflineBanner,
  CitationPill,
  JobProgress,
  StalenessBadge,
  useAiOnline,
  useGenerationJob,
} from "./common";
import { SourcesPicker } from "./SourcesPicker";
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
  deckId,
  onClose,
}: {
  card: CardOut | null; // null → add a new card to deckId
  moduleId: string;
  deckId: number;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [front, setFront] = useState(card?.front ?? "");
  const [back, setBack] = useState(card?.back ?? "");
  const save = useMutation({
    mutationFn: () =>
      card
        ? api.patch(`/api/flashcards/${card.id}`, { front, back })
        : api.post(`/api/artifacts/${deckId}/cards`, { front, back }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["deck", deckId] });
      queryClient.invalidateQueries({ queryKey: ["deck-list", moduleId] });
      queryClient.invalidateQueries({ queryKey: ["review-due-count"] });
      onClose();
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }

  return (
    <Modal title={card ? "Edit card" : "Add card"} onClose={onClose}>
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

// ── New-deck config ───────────────────────────────────────────

function NewDeckConfig({
  moduleId,
  onGenerate,
  pending,
  error,
}: {
  moduleId: string;
  onGenerate: (body: {
    count: number;
    document_ids: number[] | null;
    note_ids: number[] | null;
    instructions: string | null;
    mode: GenerationMode;
  }) => void;
  pending: boolean;
  error: string | null;
}) {
  const [count, setCount] = useState(12);
  const [docIds, setDocIds] = useState<number[] | null>(null);
  const [noteIds, setNoteIds] = useState<number[] | null>(null);
  const [instructions, setInstructions] = useState("");
  const [mode, setMode] = useState<GenerationMode>("sources");
  // Documents excluded entirely → no AI-eligible chunks → the server 409s,
  // except practice mode with a focus topic (synthesizes from nothing).
  const noSources = docIds !== null && docIds.length === 0;
  const topicOnly = mode === "exercise" && instructions.trim().length > 0;
  const blocked = noSources && !topicOnly;

  return (
    <div className="quiz-config deck-config">
      <div className="quiz-config-row">
        <span className="field-label">Cards</span>
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
      <div className="quiz-config-row">
        <span className="field-label">Materials</span>
        <SourcesPicker
          moduleId={moduleId}
          documentIds={docIds}
          noteIds={noteIds}
          onChange={(d, n) => {
            setDocIds(d);
            setNoteIds(n);
          }}
        />
      </div>
      <div className="quiz-config-row">
        <span className="field-label">Style</span>
        <div className="mode-toggle">
          <button
            type="button"
            className={`btn${mode === "sources" ? " active" : ""}`}
            onClick={() => setMode("sources")}
            title="Cards cite the exact passages they come from"
          >
            From sources (cited)
          </button>
          <button
            type="button"
            className={`btn${mode === "exercise" ? " active" : ""}`}
            onClick={() => setMode("exercise")}
            title="Original practice problems on the materials' topics — answers are AI-derived, not cited"
          >
            Practice exercises
          </button>
        </div>
      </div>
      <div className="quiz-config-row">
        <span className="field-label">Focus</span>
        <textarea
          className="input card-textarea deck-instructions"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          rows={2}
          placeholder="Optional — e.g. focus on increment/decrement operators and evaluation order"
        />
      </div>
      {count === 0 && (
        <p className="gen-hint">
          Exhaustive mode keeps generating until the material runs dry — expect
          10–20 minutes.
        </p>
      )}
      {blocked && (
        <p className="gen-hint">
          {mode === "exercise"
            ? "Add a focus topic to generate practice cards without source documents."
            : "Select at least one document — or switch to Practice exercises with a focus topic to generate without sources."}
        </p>
      )}
      {error && <p className="error-text">{error}</p>}
      <button
        className="btn btn-primary"
        onClick={() =>
          onGenerate({
            count,
            document_ids: docIds,
            note_ids: noteIds,
            instructions: instructions.trim() || null,
            mode,
          })
        }
        disabled={pending || blocked}
      >
        <Sparkle size={15} strokeWidth={1.75} /> Generate deck
      </button>
    </div>
  );
}

// ── Deck detail ───────────────────────────────────────────────

function DeckDetail({
  moduleId,
  deckId,
  onBack,
}: {
  moduleId: string;
  deckId: number;
  onBack: () => void;
}) {
  const queryClient = useQueryClient();
  const [reviewing, setReviewing] = useState(false);
  const [editing, setEditing] = useState<CardOut | null>(null);
  const [adding, setAdding] = useState(false);

  const deck = useQuery({
    queryKey: ["deck", deckId],
    queryFn: () => api.get<DeckOut>(`/api/decks/${deckId}`),
  });

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["deck", deckId] });
    queryClient.invalidateQueries({ queryKey: ["deck-list", moduleId] });
    queryClient.invalidateQueries({ queryKey: ["review-due-count"] });
  }

  const toggleReview = useMutation({
    mutationFn: (enabled: boolean) =>
      api.patch(`/api/artifacts/${deckId}`, { review_enabled: enabled }),
    onSuccess: invalidate,
  });
  const toggleSuspend = useMutation({
    mutationFn: (card: CardOut) =>
      api.patch(`/api/flashcards/${card.id}`, {
        status: card.status === "active" ? "suspended" : "active",
      }),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/api/flashcards/${id}`),
    onSuccess: invalidate,
  });

  const d = deck.data;
  const activeCards = d?.cards.filter((c) => c.status === "active") ?? [];
  const isExercise = d?.generation_mode === "exercise";

  if (reviewing && activeCards.length > 0) {
    return <ReviewMode cards={activeCards} onExit={() => setReviewing(false)} />;
  }
  if (!d) return null;

  return (
    <div className="cards-tab">
      <header className="gen-head">
        <button className="btn" onClick={onBack}>
          <ArrowLeft size={15} strokeWidth={1.75} /> Decks
        </button>
        <StalenessBadge staleness={d.staleness} />
        <span className="gen-head-meta deck-detail-title" title={d.title}>
          {d.title} · {d.cards.length} cards
        </span>
        <span className="gen-head-spacer" />
        <button
          className={`btn${d.review_enabled ? " active" : ""}`}
          onClick={() => toggleReview.mutate(!d.review_enabled)}
          title="Whether this deck's cards appear in your daily review queue"
        >
          <BookMarked size={15} strokeWidth={1.75} />
          {d.review_enabled ? "In daily review" : "Not in review"}
        </button>
        <button
          className="btn"
          onClick={() => setReviewing(true)}
          disabled={activeCards.length === 0}
        >
          <Play size={15} strokeWidth={1.75} /> Review
        </button>
        <button className="btn" onClick={() => setAdding(true)}>
          <Plus size={15} strokeWidth={1.75} /> Add card
        </button>
        <a className="btn" href={`/api/artifacts/${deckId}/export.apkg`}>
          <Download size={15} strokeWidth={1.75} /> Anki
        </a>
      </header>

      {d.instructions && (
        <p className="gen-hint deck-focus-line">Focus: {d.instructions}</p>
      )}

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
                {isExercise && card.citations.length === 0 && (
                  <span
                    className="badge stale"
                    title="AI-synthesized practice item — not cited from your materials"
                  >
                    synthesized
                  </span>
                )}
                {card.edited && <span className="badge stale">edited</span>}
              </span>
            </div>
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
          </div>
        ))}
      </div>

      {editing && (
        <CardEditor
          card={editing}
          moduleId={moduleId}
          deckId={deckId}
          onClose={() => setEditing(null)}
        />
      )}
      {adding && (
        <CardEditor
          card={null}
          moduleId={moduleId}
          deckId={deckId}
          onClose={() => setAdding(false)}
        />
      )}
    </div>
  );
}

// ── Tab (deck list) ───────────────────────────────────────────

export function FlashcardsTab({
  moduleId,
  courseId,
}: {
  moduleId: string;
  courseId: string;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const search = useSearch({ strict: false }) as { deck?: number };
  const aiOnline = useAiOnline();
  const [creating, setCreating] = useState(false);

  const decks = useQuery({
    queryKey: ["deck-list", moduleId],
    queryFn: () =>
      api.get<DeckListItem[]>(
        `/api/modules/${moduleId}/artifacts?type=flashcard_deck`,
      ),
  });

  const gen = useGenerationJob(moduleId, "generate_flashcards", () => {
    queryClient.invalidateQueries({ queryKey: ["deck-list", moduleId] });
    queryClient.invalidateQueries({ queryKey: ["review-due-count"] });
    setCreating(false);
  });

  const generate = useMutation({
    mutationFn: (body: object) =>
      api.post<JobRef>(`/api/modules/${moduleId}/flashcards/generate`, body),
    onSuccess: (ref) => gen.start(ref.job_id),
  });

  function openDeck(id: number | null) {
    navigate({
      to: "/courses/$courseId/modules/$moduleId",
      params: { courseId, moduleId },
      search: id == null ? { tab: "cards" } : { tab: "cards", deck: id },
    });
  }

  const rename = useMutation({
    mutationFn: ({ id, title }: { id: number; title: string }) =>
      api.patch(`/api/artifacts/${id}`, { title }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["deck-list", moduleId] }),
  });
  const toggleReview = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      api.patch(`/api/artifacts/${id}`, { review_enabled: enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["deck-list", moduleId] });
      queryClient.invalidateQueries({ queryKey: ["review-due-count"] });
    },
  });
  const removeDeck = useMutation({
    mutationFn: (id: number) => api.delete(`/api/artifacts/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["deck-list", moduleId] });
      queryClient.invalidateQueries({ queryKey: ["review-due-count"] });
    },
  });

  if (search.deck != null) {
    return (
      <DeckDetail
        moduleId={moduleId}
        deckId={search.deck}
        onBack={() => openDeck(null)}
      />
    );
  }

  const list = decks.data ?? [];

  return (
    <div className="cards-tab">
      <header className="gen-head">
        <span className="gen-head-meta">
          {list.length} deck{list.length === 1 ? "" : "s"}
        </span>
        <span className="gen-head-spacer" />
        <button
          className="btn btn-primary"
          onClick={() => setCreating((v) => !v)}
          disabled={gen.running}
        >
          <Plus size={15} strokeWidth={2} /> New deck
        </button>
      </header>

      {!aiOnline && (gen.running || list.length === 0) && <AiOfflineBanner />}
      {gen.running && <JobProgress job={gen.job} />}
      {gen.job?.status === "failed" && (
        <p className="error-text">Generation failed: {gen.job.error}</p>
      )}

      {(creating || (list.length === 0 && decks.isSuccess)) && !gen.running && (
        <>
          {list.length === 0 && (
            <p className="gen-hint">
              No flashcards yet. Manabi creates source-cited cards from this
              module's materials — narrow the sources, steer the focus, or
              switch to synthesized practice exercises.
            </p>
          )}
          <NewDeckConfig
            moduleId={moduleId}
            onGenerate={(body) => generate.mutate(body)}
            pending={generate.isPending}
            error={generate.isError ? (generate.error as Error).message : null}
          />
        </>
      )}

      <div className="deck-list">
        {list.map((deck) => (
          <div key={deck.artifact_id} className="deck-item">
            <button
              className="deck-item-main"
              onClick={() => openDeck(deck.artifact_id)}
            >
              <span className="deck-item-title">{deck.title}</span>
              <span className="deck-item-meta">
                {deck.item_count} cards · {deck.model_name} ·{" "}
                {new Date(deck.generated_at).toLocaleDateString()}
                {deck.review_enabled && (
                  <span className="badge deck-pill review">in review</span>
                )}
                {deck.generation_mode === "exercise" && (
                  <span className="badge deck-pill">practice</span>
                )}
              </span>
            </button>
            <div className="doc-actions">
              <button
                className={`icon-btn${deck.review_enabled ? " active" : ""}`}
                onClick={() =>
                  toggleReview.mutate({
                    id: deck.artifact_id,
                    enabled: !deck.review_enabled,
                  })
                }
                title={
                  deck.review_enabled
                    ? "Remove from daily review"
                    : "Add to daily review"
                }
                aria-label="Toggle daily review"
              >
                <BookMarked size={15} strokeWidth={1.5} />
              </button>
              <button
                className="icon-btn"
                onClick={() => {
                  const title = window.prompt("Deck name", deck.title);
                  if (title?.trim())
                    rename.mutate({ id: deck.artifact_id, title: title.trim() });
                }}
                aria-label="Rename deck"
                title="Rename"
              >
                <Pencil size={15} strokeWidth={1.5} />
              </button>
              <a
                className="icon-btn"
                href={`/api/artifacts/${deck.artifact_id}/export.apkg`}
                aria-label="Export to Anki"
                title="Export to Anki"
              >
                <Download size={15} strokeWidth={1.5} />
              </a>
              <button
                className="icon-btn danger"
                onClick={() => {
                  const warn = deck.review_enabled
                    ? `Delete "${deck.title}"? Its cards leave your daily review queue. This cannot be undone.`
                    : `Delete "${deck.title}"? This cannot be undone.`;
                  if (window.confirm(warn)) removeDeck.mutate(deck.artifact_id);
                }}
                aria-label="Delete deck"
                title="Delete"
              >
                <Trash2 size={15} strokeWidth={1.5} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
