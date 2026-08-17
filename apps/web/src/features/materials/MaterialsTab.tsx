import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  AlertCircle,
  Brain,
  BookOpen,
  CheckCircle2,
  CloudDownload,
  Columns2,
  FileText,
  Loader2,
  Presentation,
  RotateCw,
  Trash2,
  Upload,
} from "lucide-react";
import { useRef, useState } from "react";

import { Modal } from "../../components/Modal";
import { api, type DocumentOut } from "../../lib/api";
import { CanvasImportModal } from "./CanvasImportModal";
import "./materials.css";

function formatBytes(n: number): string {
  if (n > 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.round(n / 1024)} KB`;
}

function StatusChip({ doc }: { doc: DocumentOut }) {
  switch (doc.extract_status) {
    case "ready":
      return (
        <span className="chip ready">
          <CheckCircle2 size={13} strokeWidth={1.5} />
          {doc.page_count} pages
          {doc.page_layout === "spread" && (
            <span className="chip-spread" title="You split this two-page scan into single pages">
              <Columns2 size={11} strokeWidth={1.75} /> split
            </span>
          )}
          {doc.page_layout !== "spread" && doc.detected_layout === "spread" && (
            <span
              className="chip-spread"
              title="Looks like a two-page scan — use the layout control to split into single pages if you want"
            >
              <Columns2 size={11} strokeWidth={1.75} /> 2-up?
            </span>
          )}
        </span>
      );
    case "failed":
      return (
        <span className="chip failed" title={doc.error ?? undefined}>
          <AlertCircle size={13} strokeWidth={1.5} /> failed
        </span>
      );
    default:
      return (
        <span className="chip processing">
          <Loader2 size={13} strokeWidth={1.5} className="spin" />
          {doc.progress_note ?? "processing"}
        </span>
      );
  }
}

export function MaterialsTab({
  moduleId,
  onOpenDocument,
}: {
  moduleId: string;
  // When set (in a floating panel), a material opens IN the panel instead of
  // navigating the main window via the /documents route.
  onOpenDocument?: (doc: DocumentOut) => void;
}) {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<DocumentOut | null>(null);
  const [importing, setImporting] = useState(false);

  const docs = useQuery({
    queryKey: ["documents", moduleId],
    queryFn: () => api.get<DocumentOut[]>(`/api/modules/${moduleId}/documents`),
    refetchInterval: (query) =>
      query.state.data?.some(
        (d) => d.extract_status === "pending" || d.extract_status === "processing",
      )
        ? 2000
        : false,
  });

  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api.postForm<DocumentOut>(`/api/modules/${moduleId}/documents`, form);
    },
    onSuccess: () => {
      setUploadError(null);
      queryClient.invalidateQueries({ queryKey: ["documents", moduleId] });
    },
    onError: (err) => setUploadError((err as Error).message),
  });

  const retry = useMutation({
    mutationFn: (id: number) => api.post(`/api/documents/${id}/retry`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["documents", moduleId] }),
  });

  const setLayout = useMutation({
    mutationFn: (v: { id: number; page_layout: string }) =>
      api.post(`/api/documents/${v.id}/layout`, { page_layout: v.page_layout }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["documents", moduleId] }),
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/api/documents/${id}`),
    onSuccess: () => {
      setDeleting(null);
      queryClient.invalidateQueries({ queryKey: ["documents", moduleId] });
    },
  });

  const toggleAi = useMutation({
    mutationFn: (doc: DocumentOut) =>
      api.patch(`/api/documents/${doc.id}`, { ai_included: !doc.ai_included }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["documents", moduleId] }),
  });

  function pickFiles(files: FileList | null) {
    if (!files) return;
    for (const file of Array.from(files)) upload.mutate(file);
  }

  return (
    <div className="materials">
      <div
        className="upload-zone"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          pickFiles(e.dataTransfer.files);
        }}
      >
        <Upload size={20} strokeWidth={1.5} />
        <p>
          Drop PDF or PPTX files here, or{" "}
          <button className="link-btn" onClick={() => fileInput.current?.click()}>
            browse
          </button>
        </p>
        <input
          ref={fileInput}
          type="file"
          accept=".pdf,.pptx"
          multiple
          hidden
          onChange={(e) => {
            pickFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <button className="btn canvas-import-btn" onClick={() => setImporting(true)}>
          <CloudDownload size={15} strokeWidth={1.75} /> Import from Canvas
        </button>
        {upload.isPending && (
          <p className="upload-status">
            <Loader2 size={14} className="spin" /> Uploading…
          </p>
        )}
        {uploadError && <p className="error-text">{uploadError}</p>}
      </div>

      {docs.data && docs.data.length === 0 && (
        <div className="home-empty">
          <p>No materials yet. Upload your first lecture file above.</p>
        </div>
      )}

      <div className="doc-list">
        {(docs.data ?? []).map((doc) => (
          <div
            key={doc.id}
            className={`doc-row${doc.ai_included ? "" : " ai-excluded"}`}
          >
            <span className="doc-icon">
              {doc.kind === "pdf" ? (
                <FileText size={18} strokeWidth={1.5} />
              ) : (
                <Presentation size={18} strokeWidth={1.5} />
              )}
            </span>
            {doc.extract_status === "ready" ? (
              onOpenDocument ? (
                <button
                  type="button"
                  className="doc-link doc-link-btn"
                  onClick={() => onOpenDocument(doc)}
                >
                  <span className="doc-name">{doc.filename}</span>
                  <span className="doc-meta">{formatBytes(doc.byte_size)}</span>
                </button>
              ) : (
                <Link
                  to="/documents/$documentId"
                  params={{ documentId: String(doc.id) }}
                  search={{ page: 1 }}
                  className="doc-link"
                >
                  <span className="doc-name">{doc.filename}</span>
                  <span className="doc-meta">{formatBytes(doc.byte_size)}</span>
                </Link>
              )
            ) : (
              <div className="doc-link">
                <span className="doc-name">{doc.filename}</span>
                <span className="doc-meta">
                  {formatBytes(doc.byte_size)}
                  {doc.extract_status === "failed" && doc.error
                    ? ` — ${doc.error}`
                    : ""}
                </span>
              </div>
            )}
            <StatusChip doc={doc} />
            <div className="doc-actions">
              <button
                className={`icon-btn ai-toggle${doc.ai_included ? " on" : ""}`}
                onClick={() => toggleAi.mutate(doc)}
                aria-label={
                  doc.ai_included
                    ? "Included in AI generation — click to exclude"
                    : "Excluded from AI generation — click to include"
                }
                title={
                  doc.ai_included
                    ? "AI: included (summaries, cards, quizzes use this file)"
                    : "AI: excluded (this file is never used for generation)"
                }
              >
                <Brain size={15} strokeWidth={1.5} />
              </button>
              {doc.kind === "pdf" &&
                (doc.extract_status === "ready" || doc.extract_status === "failed") && (
                  <label
                    className="doc-layout"
                    title="How to read this scan: auto-detect, treat as single pages, or split two-page spreads. Changing this re-extracts the file."
                  >
                    <BookOpen size={13} strokeWidth={1.5} />
                    <select
                      value={doc.page_layout}
                      onChange={(e) => {
                        if (
                          window.confirm(
                            "Re-extract this file with the new page layout? Existing highlights on it may shift.",
                          )
                        )
                          setLayout.mutate({ id: doc.id, page_layout: e.target.value });
                      }}
                    >
                      <option value="auto">Layout: auto</option>
                      <option value="single">Single pages</option>
                      <option value="spread">Two-page spread</option>
                    </select>
                  </label>
                )}
              {doc.extract_status === "failed" && (
                <button
                  className="icon-btn"
                  onClick={() => retry.mutate(doc.id)}
                  aria-label="Retry processing"
                >
                  <RotateCw size={16} strokeWidth={1.5} />
                </button>
              )}
              <button
                className="icon-btn danger"
                onClick={() => setDeleting(doc)}
                aria-label="Delete"
              >
                <Trash2 size={16} strokeWidth={1.5} />
              </button>
            </div>
          </div>
        ))}
      </div>

      {importing && (
        <CanvasImportModal moduleId={moduleId} onClose={() => setImporting(false)} />
      )}

      {deleting && (
        <Modal title={`Remove "${deleting.filename}"?`} onClose={() => setDeleting(null)}>
          <p className="modal-danger-text">
            The file and its pages will be removed from this module.
          </p>
          <div className="modal-actions">
            <button className="btn" onClick={() => setDeleting(null)}>
              Cancel
            </button>
            <button
              className="btn btn-danger"
              onClick={() => remove.mutate(deleting.id)}
            >
              Remove
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
