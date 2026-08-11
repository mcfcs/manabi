import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { FileText, Loader2, Presentation, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";

import { api, type DocumentOut } from "../../lib/api";

interface CourseFilesOut {
  module_id: number | null;
  documents: DocumentOut[];
}

/** The course's general files (syllabus, COA, …) — stored in a hidden
 * container, viewable but excluded from modules and AI. Uploaded render-only
 * (pages are stored + viewable; no text extraction or AI generation). */
export function CourseFiles({ courseId }: { courseId: string }) {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const files = useQuery({
    queryKey: ["course-files", courseId],
    queryFn: () => api.get<CourseFilesOut>(`/api/courses/${courseId}/course-files`),
    refetchInterval: (query) =>
      query.state.data?.documents.some(
        (d) => d.extract_status === "pending" || d.extract_status === "processing",
      )
        ? 2500
        : false,
  });

  const upload = useMutation({
    mutationFn: async (file: File) => {
      // find-or-create the hidden course-files module, then upload render-only
      const { module_id } = await api.post<{ module_id: number }>(
        `/api/courses/${courseId}/course-files-module`,
      );
      const form = new FormData();
      form.append("file", file);
      form.append("processing_mode", "render_only");
      return api.postForm<DocumentOut>(`/api/modules/${module_id}/documents`, form);
    },
    onSuccess: () => {
      setUploadError(null);
      queryClient.invalidateQueries({ queryKey: ["course-files", courseId] });
    },
    onError: (err) => setUploadError((err as Error).message),
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/api/documents/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["course-files", courseId] }),
  });

  function pickFiles(list: FileList | null) {
    if (!list) return;
    for (const f of Array.from(list)) upload.mutate(f);
  }

  const docs = files.data?.documents ?? [];

  return (
    <section className="course-files">
      <div className="course-files-head-row">
        <h2 className="course-files-head">Course files</h2>
        <button
          className="btn btn-small course-files-upload"
          onClick={() => fileInput.current?.click()}
          disabled={upload.isPending}
        >
          {upload.isPending ? (
            <Loader2 size={14} className="spin" />
          ) : (
            <Upload size={14} strokeWidth={1.75} />
          )}
          Upload
        </button>
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
      </div>
      <p className="course-files-hint">
        Syllabi, course outlines, and other reference files — viewable, not used
        for AI generation.
      </p>
      {uploadError && <p className="error-text">{uploadError}</p>}

      {docs.length === 0 ? (
        <div
          className="course-files-drop"
          onClick={() => fileInput.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            pickFiles(e.dataTransfer.files);
          }}
        >
          <Upload size={18} strokeWidth={1.5} />
          <span>Drop a PDF or PPTX here, or click to upload</span>
        </div>
      ) : (
        <div className="course-files-row">
          {docs.map((doc) => (
            <div key={doc.id} className="course-file-card">
              <span className="doc-icon">
                {doc.kind === "pdf" ? (
                  <FileText size={16} strokeWidth={1.5} />
                ) : (
                  <Presentation size={16} strokeWidth={1.5} />
                )}
              </span>
              {doc.extract_status === "ready" ? (
                <Link
                  to="/documents/$documentId"
                  params={{ documentId: String(doc.id) }}
                  search={{ page: 1 }}
                  className="course-file-name"
                  title={doc.filename}
                >
                  {doc.filename}
                </Link>
              ) : (
                <span className="course-file-name" title={doc.filename}>
                  {doc.filename}
                  {(doc.extract_status === "pending" ||
                    doc.extract_status === "processing") && (
                    <Loader2 size={12} className="spin" />
                  )}
                </span>
              )}
              <button
                className="icon-btn danger course-file-delete"
                onClick={() => remove.mutate(doc.id)}
                aria-label={`Delete ${doc.filename}`}
              >
                <Trash2 size={13} strokeWidth={1.5} />
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
