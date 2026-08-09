import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Wand2 } from "lucide-react";
import { useState } from "react";

import { Modal } from "../../components/Modal";
import { api } from "../../lib/api";

export function GenerateAllModal({
  moduleId,
  onClose,
}: {
  moduleId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [summary, setSummary] = useState(true);
  const [cards, setCards] = useState(true);
  const [cardCount, setCardCount] = useState(12);
  const [quiz, setQuiz] = useState(false);
  const [quizCount, setQuizCount] = useState(10);

  const run = useMutation({
    mutationFn: () =>
      api.post<{ jobs: Record<string, number> }>(
        `/api/modules/${moduleId}/generate-all`,
        {
          summary,
          flashcards_count: cards ? cardCount : null,
          quiz_count: quiz ? quizCount : null,
          quiz_types: ["mcq", "tf", "short"],
        },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["active-jobs", moduleId] });
      onClose();
    },
  });

  const nothing = !summary && !cards && !quiz;

  return (
    <Modal title="Generate study kit" onClose={onClose}>
      <div className="modal-form">
        <label className="quiz-check">
          <input
            type="checkbox"
            checked={summary}
            onChange={(e) => setSummary(e.target.checked)}
          />
          Summary (with key terms &amp; acronyms)
        </label>
        <label className="quiz-check">
          <input
            type="checkbox"
            checked={cards}
            onChange={(e) => setCards(e.target.checked)}
          />
          Flashcards
          {cards && (
            <select
              className="input quiz-count"
              value={cardCount}
              onChange={(e) => setCardCount(Number(e.target.value))}
            >
              {[8, 12, 16, 20].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          )}
        </label>
        <label className="quiz-check">
          <input
            type="checkbox"
            checked={quiz}
            onChange={(e) => setQuiz(e.target.checked)}
          />
          Quiz
          {quiz && (
            <select
              className="input quiz-count"
              value={quizCount}
              onChange={(e) => setQuizCount(Number(e.target.value))}
            >
              {[5, 10, 15].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          )}
        </label>

        <p className="gen-hint">
          Generated one after another on the AI node. Your notes guide emphasis —
          they are never treated as source material.
        </p>
        {run.isError && <p className="error-text">{(run.error as Error).message}</p>}

        <div className="modal-actions">
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            disabled={nothing || run.isPending}
            onClick={() => run.mutate()}
          >
            <Wand2 size={15} strokeWidth={1.75} /> Generate
          </button>
        </div>
      </div>
    </Modal>
  );
}
