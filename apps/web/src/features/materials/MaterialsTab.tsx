import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  AlertCircle,
  CheckCircle2,
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

export function MaterialsTab({ moduleId }: { moduleId: string }) {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<DocumentOut | null>(null);

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

  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/api/documents/${id}`),
    onSuccess: () => {
      setDeleting(null);
      queryClient.invalidateQueries({ queryKey: ["documents", moduleId] });
    },
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
          <div key={doc.id} className="doc-row">
            <span className="doc-icon">
              {doc.kind === "pdf" ? (
                <FileText size={18} strokeWidth={1.5} />
              ) : (
                <Presentation size={18} strokeWidth={1.5} />
              )}
            </span>
            {doc.extract_status === "ready" ? (
              <Link
                to="/documents/$documentId"
                params={{ documentId: String(doc.id) }}
                search={{ page: 1 }}
                className="doc-link"
              >
                <span className="doc-name">{doc.filename}</span>
                <span className="doc-meta">{formatBytes(doc.byte_size)}</span>
              </Link>
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
