import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Modal } from "../../components/Modal";
import {
  api,
  ApiError,
  type CourseGradesOut,
  type GradesOverviewOut,
} from "../../lib/api";

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
  const [applyTo, setApplyTo] = useState<Set<number>>(new Set());
  const [applied, setApplied] = useState<string[] | null>(null);

  // Six numbers per course, retyped each time. Courses in the same department
  // usually share a scheme, so offer to copy this one across.
  const others = useQuery({
    queryKey: ["grades-overview"],
    queryFn: () => api.get<GradesOverviewOut>("/api/grades"),
    staleTime: 60_000,
  });

  const apply = useMutation({
    mutationFn: () =>
      api.post<{ applied: string[] }>(
        `/api/courses/${grades.course_id}/grades/cutoffs/apply`,
        { course_ids: [...applyTo] },
      ),
    onSuccess: (r) => {
      setApplied(r.applied);
      setApplyTo(new Set());
      queryClient.invalidateQueries({ queryKey: ["grades-overview"] });
    },
  });

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

        {grades.cutoffs && (others.data?.courses.length ?? 0) > 1 && (
          <details className="scheme-copy">
            <summary>Also apply this scheme to…</summary>
            {(others.data?.courses ?? [])
              .filter((c) => c.course_id !== grades.course_id)
              .map((c) => (
                <label key={c.course_id} className="scheme-copy-row">
                  <input
                    type="checkbox"
                    checked={applyTo.has(c.course_id)}
                    onChange={() => {
                      const next = new Set(applyTo);
                      if (next.has(c.course_id)) next.delete(c.course_id);
                      else next.add(c.course_id);
                      setApplyTo(next);
                    }}
                  />
                  <span>{c.code}</span>
                  {c.has_cutoffs && <span className="scheme-copy-warn">has one already</span>}
                </label>
              ))}
            <button
              className="btn btn-sm"
              disabled={applyTo.size === 0 || apply.isPending}
              onClick={() => apply.mutate()}
            >
              Copy to {applyTo.size} course{applyTo.size === 1 ? "" : "s"}
            </button>
            {applied && (
              <p className="scheme-copy-done">
                {applied.length ? `Copied to ${applied.join(", ")}.` : "Nothing to copy."}
              </p>
            )}
          </details>
        )}

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
