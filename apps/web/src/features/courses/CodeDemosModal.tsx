import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Code2, Loader2 } from "lucide-react";

import { Modal } from "../../components/Modal";
import { api, ApiError, type CourseOut } from "../../lib/api";

interface DemoRow {
  title: string;
  canvas_module: string;
  module_id: number | null;
  files: string[];
  status: string | null;
  document_id?: number;
}

/** Import the professor's demo code: Canvas pages that link .c/.cpp files or
 * zips, and loose code files in modules. Canvas is only read; each demo page
 * becomes one code material in its module, kept byte-for-byte, so quizzes
 * can trace his programs and write code in his style. */
export function CodeDemosModal({ course, onClose }: { course: CourseOut; onClose: () => void }) {
  const queryClient = useQueryClient();
  const url = `/api/canvas/courses/${course.id}/canvas/code-demos`;
  const preview = useQuery({
    queryKey: ["code-demos-preview", course.id],
    queryFn: () => api.post<DemoRow[]>(url, { dry_run: true }),
    staleTime: 60_000,
  });
  const run = useMutation({
    mutationFn: () => api.post<DemoRow[]>(url, { dry_run: false }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["modules", String(course.id)] });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
  const rows = run.data ?? preview.data ?? [];
  const importable = rows.filter((r) => r.module_id != null).length;
  const error = (run.error ?? preview.error) as ApiError | Error | null;

  return (
    <Modal title="Import code demos" onClose={onClose} wide>
      <p className="gen-hint">
        Demo programs linked from this course's Canvas pages (zips are unpacked). Each page
        becomes one code material in its module, exactly as the professor wrote it. Canvas is
        only read.
      </p>
      {preview.isLoading && (
        <p className="gen-hint">
          <Loader2 size={14} className="spin" /> Looking through the course's pages…
        </p>
      )}
      {error && <p className="error-text">{error.message}</p>}
      {!preview.isLoading && rows.length === 0 && !error && (
        <p className="gen-hint">No demo code found on this course's Canvas pages.</p>
      )}
      {rows.length > 0 && (
        <ul className="code-demo-list">
          {rows.map((r) => (
            <li key={`${r.canvas_module}-${r.title}`}>
              <div className="code-demo-head">
                <Code2 size={15} strokeWidth={1.75} />
                <span className="code-demo-title">{r.title}</span>
                <span className="code-demo-status">
                  {r.status === "planned"
                    ? r.module_id == null
                      ? "no matching module — skipped"
                      : r.canvas_module
                    : r.status}
                </span>
              </div>
              <p className="code-demo-files">{r.files.join(" · ")}</p>
            </li>
          ))}
        </ul>
      )}
      <div className="modal-actions">
        <button type="button" className="btn" onClick={onClose}>
          {run.isSuccess ? "Done" : "Cancel"}
        </button>
        {!run.isSuccess && (
          <button
            type="button"
            className="btn btn-primary"
            disabled={!importable || run.isPending || preview.isLoading}
            onClick={() => run.mutate()}
          >
            {run.isPending && <Loader2 size={14} className="spin" />} Import {importable}{" "}
            {importable === 1 ? "demo" : "demos"}
          </button>
        )}
      </div>
    </Modal>
  );
}
