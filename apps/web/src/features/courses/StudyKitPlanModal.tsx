import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Modal } from "../../components/Modal";
import { api, type CourseKitPlan } from "../../lib/api";

/** Queue study kits across a course — but only after showing exactly what
 * would run. Generation is expensive and shares the GPU with everything else,
 * so nothing is queued from a single click. */
export function StudyKitPlanModal({
  courseId,
  onClose,
}: {
  courseId: number;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [chosen, setChosen] = useState<Set<number> | null>(null);
  const [queued, setQueued] = useState<number | null>(null);

  const plan = useQuery({
    queryKey: ["study-kit-plan", courseId],
    queryFn: () => api.get<CourseKitPlan>(`/api/courses/${courseId}/study-kit-plan`),
  });

  const candidates = plan.data?.candidates ?? [];
  const picked = chosen ?? new Set(candidates.map((c) => c.module_id));

  const run = useMutation({
    mutationFn: () =>
      api.post<{ modules: number }>(`/api/courses/${courseId}/generate-study-kits`, {
        module_ids: [...picked],
      }),
    onSuccess: (r) => {
      setQueued(r.modules);
      qc.invalidateQueries({ queryKey: ["modules"] });
      qc.invalidateQueries({ queryKey: ["global-active-jobs"] });
    },
  });

  function toggle(id: number) {
    const next = new Set(picked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChosen(next);
  }

  return (
    <Modal title="Generate study kits" onClose={onClose}>
      {plan.isLoading && <p className="gen-hint">Checking which modules need one…</p>}

      {queued != null ? (
        <>
          <p>
            Queued for <b>{queued}</b> module{queued === 1 ? "" : "s"}. They run one at a time on
            the GPU; watch progress under Activity.
          </p>
          <div className="modal-actions">
            <button className="btn btn-primary" onClick={onClose}>
              Done
            </button>
          </div>
        </>
      ) : (
        plan.data && (
          <>
            {candidates.length === 0 ? (
              <p className="gen-hint">
                Every module with materials already has a summary and cards.
              </p>
            ) : (
              <>
                <p className="gen-hint">
                  This queues a summary and flashcards for each module you leave ticked. Nothing
                  runs until you confirm.
                </p>
                <ul className="kit-plan-list">
                  {candidates.map((c) => (
                    <li key={c.module_id}>
                      <label className="kit-plan-row">
                        <input
                          type="checkbox"
                          checked={picked.has(c.module_id)}
                          onChange={() => toggle(c.module_id)}
                        />
                        <span className="kit-plan-title">{c.title}</span>
                        <span className="kit-plan-meta mono">
                          {c.document_count} doc{c.document_count === 1 ? "" : "s"}
                          {c.has_summary ? " · has summary" : ""}
                          {c.card_count > 0 ? ` · ${c.card_count} cards` : ""}
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              </>
            )}

            {(plan.data.skipped_no_materials.length > 0 ||
              plan.data.skipped_have_kit.length > 0) && (
              <p className="kit-plan-skipped">
                {plan.data.skipped_have_kit.length > 0 && (
                  <>
                    Already done: {plan.data.skipped_have_kit.join(", ")}.{" "}
                  </>
                )}
                {plan.data.skipped_no_materials.length > 0 && (
                  <>No materials yet: {plan.data.skipped_no_materials.join(", ")}.</>
                )}
              </p>
            )}

            <div className="modal-actions">
              <button className="btn" onClick={onClose}>
                Cancel
              </button>
              <button
                className="btn btn-primary"
                onClick={() => run.mutate()}
                disabled={picked.size === 0 || run.isPending}
              >
                {run.isPending
                  ? "Queueing…"
                  : `Generate for ${picked.size} module${picked.size === 1 ? "" : "s"}`}
              </button>
            </div>
          </>
        )
      )}
    </Modal>
  );
}
