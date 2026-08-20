import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Link as LinkIcon, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { api } from "../../lib/api";

interface CourseLinkOut {
  id: number;
  course_id: number;
  module_id: number | null;
  title: string;
  url: string;
  canvas_item_id: number | null;
}

/** Openable resource links for a course — Canvas ExternalUrl module-items
 * (populated by Sync) plus manually added URLs. */
export function CourseLinks({ courseId }: { courseId: string }) {
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");

  const links = useQuery({
    queryKey: ["links", courseId],
    queryFn: () => api.get<CourseLinkOut[]>(`/api/courses/${courseId}/links`),
  });
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["links", courseId] });

  const add = useMutation({
    mutationFn: () =>
      api.post(`/api/courses/${courseId}/links`, { title: title.trim(), url: url.trim() }),
    onSuccess: () => {
      setTitle("");
      setUrl("");
      setAdding(false);
      invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/api/links/${id}`),
    onSuccess: invalidate,
  });

  const data = links.data ?? [];
  if (data.length === 0 && !adding) {
    return (
      <div className="course-links course-links-empty">
        <button className="link-btn" onClick={() => setAdding(true)}>
          <Plus size={13} strokeWidth={1.75} /> Add a link
        </button>
      </div>
    );
  }

  return (
    <section className="course-links">
      <div className="course-links-head">
        <h2>
          <LinkIcon size={15} strokeWidth={1.75} /> Links
        </h2>
        <button className="link-btn" onClick={() => setAdding((v) => !v)}>
          <Plus size={13} strokeWidth={1.75} /> Add
        </button>
      </div>

      {adding && (
        <form
          className="course-link-add"
          onSubmit={(e) => {
            e.preventDefault();
            if (url.trim()) add.mutate();
          }}
        >
          <input
            className="input"
            placeholder="Title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <input
            className="input"
            placeholder="https://…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <button className="btn" disabled={!url.trim() || add.isPending}>
            Add
          </button>
        </form>
      )}

      <div className="course-link-list">
        {data.map((l) => (
          <div key={l.id} className="course-link-row">
            <a
              className="course-link-open"
              href={l.url}
              target="_blank"
              rel="noreferrer"
              title={l.url}
            >
              <ExternalLink size={14} strokeWidth={1.75} />
              <span className="course-link-title">{l.title}</span>
            </a>
            <button
              className="icon-btn danger"
              onClick={() => remove.mutate(l.id)}
              aria-label="Remove link"
            >
              <Trash2 size={14} strokeWidth={1.5} />
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}
