import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Modal } from "../../components/Modal";
import { api, ApiError, type CourseGradesOut } from "../../lib/api";

/** The six graded letters, best first. F is implicit: anything below D. */
const LETTERS = ["A", "B+", "B", "C+", "C", "D"] as const;

/** Edit one course's letter cutoffs. The ladder is always A/B+/B/C+/C/D/F —
 * only the minimums change, and they come from that course's syllabus. */
export function SchemeEditor({
  grades,
  onClose,
}: {
  grades: CourseGradesOut;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const start = grades.cutoffs ?? grades.default_cutoffs;
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(LETTERS.map((l) => [l, String(start[l] ?? "")])),
  );
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () =>
      api.put<CourseGradesOut>(`/api/courses/${grades.course_id}/grades/cutoffs`, {
        cutoffs: Object.fromEntries(LETTERS.map((l) => [l, Number(values[l])])),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["grades", String(grades.course_id)], data);
      queryClient.invalidateQueries({ queryKey: ["grades-overview"] });
      onClose();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not save the scheme"),
  });

  const numbers = LETTERS.map((l) => Number(values[l]));
  const complete = numbers.every((n) => Number.isFinite(n) && n >= 0 && n <= 100);
  const descending = numbers.every((n, i) => i === 0 || n < numbers[i - 1]);

  return (
    <Modal title={`Grading scheme — ${grades.code}`} onClose={onClose}>
      <div className="modal-form">
        <p className="settings-hint">
          The lowest percentage that still earns each letter, from this course's syllabus.
          Anything below D is an F.
        </p>
        <div className="scheme-rows">
          {LETTERS.map((letter, i) => (
            <label key={letter} className="scheme-row">
              <span className="scheme-letter">{letter}</span>
              <span className="scheme-from">from</span>
              <input
                className="input scheme-input"
                type="number"
                inputMode="decimal"
                min={0}
                max={100}
                step="0.1"
                value={values[letter]}
                onChange={(e) => setValues((v) => ({ ...v, [letter]: e.target.value }))}
              />
              <span className="scheme-upto">
                {i === 0 ? "and up" : `up to ${(Number(values[LETTERS[i - 1]]) - 0.01).toFixed(2)}`}
              </span>
            </label>
          ))}
          <div className="scheme-row scheme-row-f">
            <span className="scheme-letter">F</span>
            <span className="scheme-from">below</span>
            <span className="scheme-input scheme-implicit">{values.D || "—"}</span>
          </div>
        </div>

        {!descending && complete && (
          <p className="error-text">Each letter must sit below the one above it.</p>
        )}
        {error && <p className="error-text">{error}</p>}

        <div className="modal-actions">
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            disabled={!complete || !descending || save.isPending}
            onClick={() => save.mutate()}
          >
            Save scheme
          </button>
        </div>
      </div>
    </Modal>
  );
}
