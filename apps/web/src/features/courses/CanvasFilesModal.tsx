import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CloudDownload, Loader2 } from "lucide-react";
import { useState } from "react";

import { Modal } from "../../components/Modal";
import { api, ApiError, type CourseOut, type ModuleOut } from "../../lib/api";

interface CanvasFile {
  id: number;
  filename: string;
  size: number;
  updated_at: string | null;
}

const SKIP = "";
const COURSE_FILES = "__coursefiles__";

interface RowChoice {
  dest: string; // "" skip · module id · "__general__"
  ai: boolean;
  extract: boolean;
}

function formatBytes(n: number): string {
  if (n > 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.round(n / 1024)} KB`;
}

/** Course-level Canvas file manager: pull every PDF/PPTX in the Canvas
 * course, choose a destination module (or a new "General"), and decide per
 * file whether it gets text extraction / AI or is stored view-only. */
export function CanvasFilesModal({
  course,
  onClose,
}: {
  course: CourseOut;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const canvasCourseId = course.canvas_url?.split("/").pop();
  const [choices, setChoices] = useState<Map<number, RowChoice>>(new Map());
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const files = useQuery({
    queryKey: ["canvas-files", canvasCourseId],
    queryFn: () =>
      api.get<CanvasFile[]>(`/api/canvas/courses/${canvasCourseId}/files`),
    enabled: !!canvasCourseId,
    retry: false,
  });
  const modules = useQuery({
    queryKey: ["modules", String(course.id)],
    queryFn: () => api.get<ModuleOut[]>(`/api/courses/${course.id}/modules`),
  });

  const choice = (id: number): RowChoice =>
    choices.get(id) ?? { dest: SKIP, ai: true, extract: true };

  const setChoice = (id: number, patch: Partial<RowChoice>) =>
    setChoices((prev) => {
      const next = new Map(prev);
      const current = { ...choice(id), ...patch };
      // Course files (syllabus, COA, …): extraction + AI default OFF
      if (patch.dest === COURSE_FILES) {
        current.extract = false;
        current.ai = false;
      } else if (patch.dest && patch.dest !== SKIP) {
        current.extract = true;
        current.ai = true;
      }
      next.set(id, current);
      return next;
    });

  const selected = (files.data ?? []).filter((f) => choice(f.id).dest !== SKIP);

  const runImport = useMutation({
    mutationFn: async () => {
      let courseFilesId: number | null = null;
      let done = 0;
      for (const f of selected) {
        const c = choice(f.id);
        let moduleId = c.dest === COURSE_FILES ? courseFilesId : Number(c.dest);
        if (c.dest === COURSE_FILES && moduleId == null) {
          const created = await api.post<{ module_id: number }>(
            `/api/courses/${course.id}/course-files-module`,
          );
          courseFilesId = created.module_id;
          moduleId = created.module_id;
        }
        setProgress(`Importing ${++done} of ${selected.length}…`);
        try {
          await api.post(`/api/canvas/modules/${moduleId}/import`, {
            file_id: f.id,
            ai_included: c.ai,
            extract_text: c.extract,
          });
        } catch (e) {
          if (!(e instanceof ApiError && e.status === 409)) throw e; // dedup ok
        }
      }
      queryClient.invalidateQueries({ queryKey: ["modules", String(course.id)] });
      queryClient.invalidateQueries({ queryKey: ["course-files", String(course.id)] });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
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

  return (
    <Modal title={`Canvas files — ${course.code}`} onClose={onClose} wide>
      <div className="modal-form">
        {files.isLoading && (
          <p className="gen-hint">
            <Loader2 size={13} className="spin" /> Loading files from Canvas…
          </p>
        )}
        {files.isError && (
          <p className="error-text">
            {files.error instanceof ApiError
              ? files.error.message
              : "Could not reach Canvas"}
          </p>
        )}
        {files.data && files.data.length === 0 && (
          <p className="gen-hint">No PDF or PPTX files in this Canvas course.</p>
        )}

        {files.data && files.data.length > 0 && (
          <div className="canvas-mgr-list">
            <div className="canvas-mgr-row canvas-mgr-headrow">
              <span>File</span>
              <span>Destination</span>
              <span title="Text extraction (needed for summaries, search, chat)">
                Extract
              </span>
              <span title="Available to AI generation">AI</span>
            </div>
            {files.data.map((f) => {
              const c = choice(f.id);
              return (
                <div key={f.id} className="canvas-mgr-row">
                  <span className="canvas-mgr-name" title={f.filename}>
                    {f.filename}
                    <span className="canvas-file-size mono">{formatBytes(f.size)}</span>
                  </span>
                  <select
                    className="input canvas-mgr-dest"
                    value={c.dest}
                    onChange={(e) => setChoice(f.id, { dest: e.target.value })}
                  >
                    <option value={SKIP}>— skip —</option>
                    <option value={COURSE_FILES}>Course files</option>
                    {(modules.data ?? []).map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.title.slice(0, 30)}
                      </option>
                    ))}
                  </select>
                  <input
                    type="checkbox"
                    checked={c.extract}
                    disabled={c.dest === SKIP}
                    onChange={(e) =>
                      setChoice(f.id, {
                        extract: e.target.checked,
                        ai: e.target.checked ? c.ai : false,
                      })
                    }
                    aria-label="Extract text"
                  />
                  <input
                    type="checkbox"
                    checked={c.ai && c.extract}
                    disabled={c.dest === SKIP || !c.extract}
                    onChange={(e) => setChoice(f.id, { ai: e.target.checked })}
                    aria-label="Include in AI"
                  />
                </div>
              );
            })}
          </div>
        )}

        <p className="gen-hint">
          "Course files" = the course's general area (syllabus, COA, …) —
          extraction and AI default off there; the built-in PDF view still
          supports Ctrl+F. Modules default to full extraction.
        </p>

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
            disabled={selected.length === 0 || runImport.isPending}
            onClick={() => runImport.mutate()}
          >
            <CloudDownload size={15} strokeWidth={1.75} /> Import
            {selected.length > 0 ? ` (${selected.length})` : ""}
          </button>
        </div>
      </div>
    </Modal>
  );
}
