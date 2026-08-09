import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { FileText, Loader2, Presentation, Trash2 } from "lucide-react";

import { api, type DocumentOut } from "../../lib/api";

interface CourseFilesOut {
  module_id: number | null;
  documents: DocumentOut[];
}

/** The course's general files (syllabus, COA, …) — stored in a hidden
 * container, viewable but excluded from modules and AI by default. */
export function CourseFiles({ courseId }: { courseId: string }) {
  const queryClient = useQueryClient();
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
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/api/documents/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["course-files", courseId] }),
  });

  const docs = files.data?.documents ?? [];
  if (docs.length === 0) return null;

  return (
    <section className="course-files">
      <h2 className="course-files-head">Course files</h2>
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
    </section>
  );
}
