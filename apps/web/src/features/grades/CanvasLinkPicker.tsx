import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";

import { Modal } from "../../components/Modal";
import { api, ApiError, type CanvasAssignmentOut } from "../../lib/api";
import { fmtPercent } from "./grades";

/** Pick Canvas assignments to attach to one component. Their scores are
 * pulled immediately and refreshed by "Sync grades" afterwards. */
export function CanvasLinkPicker({
  courseId,
  componentId,
  componentName,
  onClose,
}: {
  courseId: number;
  componentId: number;
  componentName: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const assignments = useQuery({
    queryKey: ["canvas-assignments", String(courseId)],
    queryFn: () =>
      api.get<CanvasAssignmentOut[]>(`/api/courses/${courseId}/grades/canvas-assignments`),
    retry: false,
  });

  const link = useMutation({
    mutationFn: () =>
      api.post(`/api/grades/components/${componentId}/link`, {
        canvas_assignment_ids: [...picked],
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["grades", String(courseId)] });
      queryClient.invalidateQueries({ queryKey: ["grades-overview"] });
      onClose();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not link those"),
  });

  function toggle(id: number) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const rows = assignments.data ?? [];
  const available = rows.filter((a) => !a.already_linked);

  return (
    <Modal title={`Add to ${componentName}`} onClose={onClose}>
      <div className="modal-form">
        {assignments.isLoading && (
          <p className="gen-hint">
            <Loader2 size={13} className="spin" /> Reading Canvas…
          </p>
        )}
        {assignments.isError && (
          <p className="error-text">
            {assignments.error instanceof ApiError
              ? assignments.error.message
              : "Could not reach Canvas"}
          </p>
        )}
        {assignments.data && available.length === 0 && (
          <p className="gen-hint">
            {rows.length === 0
              ? "Canvas has no assignments for this course yet."
              : "Every Canvas assignment is already linked somewhere in this course."}
          </p>
        )}

        {available.length > 0 && (
          <div className="link-list">
            {rows.map((a) => (
              <label
                key={a.canvas_assignment_id}
                className={`quiz-check link-row${a.already_linked ? " linked" : ""}`}
                title={
                  a.already_linked ? `Already in ${a.linked_component}` : undefined
                }
              >
                <input
                  type="checkbox"
                  checked={picked.has(a.canvas_assignment_id)}
                  disabled={a.already_linked}
                  onChange={() => toggle(a.canvas_assignment_id)}
                />
                <span className="link-name">{a.name}</span>
                <span className="link-score mono">
                  {a.already_linked
                    ? `in ${a.linked_component}`
                    : a.graded
                      ? `${a.score} / ${a.points_possible ?? "—"}`
                      : a.points_possible != null
                        ? `— / ${a.points_possible}`
                        : "no points"}
                </span>
              </label>
            ))}
          </div>
        )}

        {error && <p className="error-text">{error}</p>}

        <div className="modal-actions">
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            disabled={picked.size === 0 || link.isPending}
            onClick={() => link.mutate()}
          >
            {link.isPending && <Loader2 size={14} className="spin" />} Add{" "}
            {picked.size > 0 ? `(${picked.size})` : ""}
          </button>
        </div>
      </div>
    </Modal>
  );
}

/** Small helper shared with the section: a score line for a linked row. */
export function canvasScoreLabel(a: CanvasAssignmentOut): string {
  return a.graded && a.points_possible
    ? fmtPercent((100 * (a.score ?? 0)) / a.points_possible)
    : "not graded yet";
}
