import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CloudDownload, Loader2 } from "lucide-react";
import { useState } from "react";

import { Modal } from "../../components/Modal";
import { api, ApiError } from "../../lib/api";

interface CanvasCourse {
  id: number;
  name: string;
  course_code: string | null;
}

interface CanvasFile {
  id: number;
  filename: string;
  size: number;
  updated_at: string | null;
}

function formatBytes(n: number): string {
  if (n > 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.round(n / 1024)} KB`;
}

export function CanvasImportModal({
  moduleId,
  onClose,
}: {
  moduleId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [courseId, setCourseId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const courses = useQuery({
    queryKey: ["canvas-courses"],
    queryFn: () => api.get<CanvasCourse[]>("/api/canvas/courses"),
    staleTime: 5 * 60_000,
    retry: false,
  });

  const files = useQuery({
    queryKey: ["canvas-files", courseId],
    queryFn: () => api.get<CanvasFile[]>(`/api/canvas/courses/${courseId}/files`),
    enabled: courseId != null,
    staleTime: 60_000,
    retry: false,
  });

  const runImport = useMutation({
    mutationFn: async () => {
      const ids = [...selected];
      for (let i = 0; i < ids.length; i++) {
        setProgress(`Importing ${i + 1} of ${ids.length}…`);
        try {
          await api.post(`/api/canvas/modules/${moduleId}/import`, {
            file_id: ids[i],
          });
        } catch (e) {
          // dedup 409s are fine — the file is already there
          if (!(e instanceof ApiError && e.status === 409)) throw e;
        }
        queryClient.invalidateQueries({ queryKey: ["documents", moduleId] });
      }
    },
    onSuccess: () => {
      setProgress(null);
      onClose();
    },
    onError: (e) => {
      setProgress(null);
      setError(e instanceof ApiError ? e.message : "Import failed");
    },
  });

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <Modal title="Import from Canvas" onClose={onClose}>
      <div className="modal-form">
        {courses.isError && (
          <p className="error-text">
            {courses.error instanceof ApiError
              ? courses.error.message
              : "Could not reach Canvas"}
          </p>
        )}
        {courses.isLoading && (
          <p className="gen-hint">
            <Loader2 size={13} className="spin" /> Loading your Canvas courses…
          </p>
        )}

        {courses.data && (
          <select
            className="input"
            value={courseId ?? ""}
            onChange={(e) => {
              setCourseId(e.target.value ? Number(e.target.value) : null);
              setSelected(new Set());
            }}
          >
            <option value="">Choose a Canvas course…</option>
            {courses.data.map((c) => (
              <option key={c.id} value={c.id}>
                {c.course_code ? `${c.course_code} — ` : ""}
                {c.name.slice(0, 60)}
              </option>
            ))}
          </select>
        )}

        {files.isLoading && (
          <p className="gen-hint">
            <Loader2 size={13} className="spin" /> Loading files…
          </p>
        )}
        {files.data && files.data.length === 0 && (
          <p className="gen-hint">No PDF or PPTX files in this Canvas course.</p>
        )}
        {files.data && files.data.length > 0 && (
          <div className="canvas-file-list">
            {files.data.map((f) => (
              <label key={f.id} className="quiz-check canvas-file">
                <input
                  type="checkbox"
                  checked={selected.has(f.id)}
                  onChange={() => toggle(f.id)}
                />
                <span className="canvas-file-name">{f.filename}</span>
                <span className="canvas-file-size mono">{formatBytes(f.size)}</span>
              </label>
            ))}
          </div>
        )}

        {progress && (
          <p className="gen-hint">
            <Loader2 size={13} className="spin" /> {progress}
          </p>
        )}
        {error && <p className="error-text">{error}</p>}

        <div className="modal-actions">
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            disabled={selected.size === 0 || runImport.isPending}
            onClick={() => runImport.mutate()}
          >
            <CloudDownload size={15} strokeWidth={1.75} /> Import{" "}
            {selected.size > 0 ? `(${selected.size})` : ""}
          </button>
        </div>
      </div>
    </Modal>
  );
}
