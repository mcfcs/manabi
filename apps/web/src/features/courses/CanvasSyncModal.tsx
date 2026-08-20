import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CloudDownload,
  FileText,
  Link as LinkIcon,
  Loader2,
  MessagesSquare,
  ScrollText,
} from "lucide-react";
import { useState } from "react";

import { Modal } from "../../components/Modal";
import { api, ApiError, type CourseOut } from "../../lib/api";

interface CanvasItem {
  canvas_item_id: number;
  type: string; // File | Page | ExternalUrl | Discussion | Assignment | Quiz | …
  title: string;
  content_id: number | null;
  page_url: string | null;
  external_url: string | null;
  html_url: string | null;
}
interface CanvasModuleT {
  canvas_id: number;
  name: string;
  position: number;
  items: CanvasItem[];
}
interface CanvasStructure {
  modules: CanvasModuleT[];
  pages: { url: string; title: string }[];
  discussions: { id: number; title: string }[];
  has_syllabus: boolean;
}

const SUPPORTED = new Set(["File", "Page", "ExternalUrl", "Discussion"]);
const ICON: Record<string, typeof FileText> = {
  File: FileText,
  Page: ScrollText,
  ExternalUrl: LinkIcon,
  Discussion: MessagesSquare,
};

function supportedItems(m: CanvasModuleT): CanvasItem[] {
  return m.items.filter((it) => SUPPORTED.has(it.type));
}

/** Deeper Canvas sync: mirror the course's module ("topic") structure into
 * Manabi, pulling each module's files, pages, links, and discussions — plus
 * standalone pages/discussions and the syllabus. */
export function CanvasSyncModal({
  course,
  onClose,
}: {
  course: CourseOut;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const cid = course.canvas_url?.split("/").pop();
  const [selMods, setSelMods] = useState<Set<number>>(new Set());
  const [selPages, setSelPages] = useState<Set<string>>(new Set());
  const [selDiscs, setSelDiscs] = useState<Set<number>>(new Set());
  const [syllabus, setSyllabus] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [failures, setFailures] = useState<string[]>([]);

  const structure = useQuery({
    queryKey: ["canvas-structure", cid],
    queryFn: () => api.get<CanvasStructure>(`/api/canvas/courses/${cid}/structure`),
    enabled: !!cid,
    retry: false,
  });

  const toggle = <T,>(set: (u: (p: Set<T>) => Set<T>) => void, v: T) =>
    set((prev) => {
      const next = new Set(prev);
      next.has(v) ? next.delete(v) : next.add(v);
      return next;
    });

  const s = structure.data;
  const totalSelected =
    (s?.modules ?? [])
      .filter((m) => selMods.has(m.canvas_id))
      .reduce((n, m) => n + supportedItems(m).length, 0) +
    selPages.size +
    selDiscs.size +
    (syllabus ? 1 : 0);

  const run = useMutation({
    mutationFn: async () => {
      if (!s) return;
      setFailures([]);
      const fails: string[] = [];
      let done = 0;
      const step = async (label: string, fn: () => Promise<unknown>) => {
        setProgress(`Importing ${++done} of ${totalSelected} — ${label}`);
        try {
          await fn();
        } catch (e) {
          if (e instanceof ApiError && e.status === 409) return; // already there
          fails.push(`${label}: ${e instanceof ApiError ? e.message : "failed"}`);
        }
      };

      // 1. Create/dedup a Manabi module per selected Canvas module.
      const chosen = s.modules.filter((m) => selMods.has(m.canvas_id));
      const mapping = new Map<number, number>();
      if (chosen.length) {
        const res = await api.post<{ canvas_id: number; module_id: number }[]>(
          "/api/canvas/sync-modules",
          {
            course_id: course.id,
            modules: chosen.map((m) => ({
              canvas_id: m.canvas_id,
              name: m.name,
              position: m.position,
            })),
          },
        );
        for (const r of res) mapping.set(r.canvas_id, r.module_id);
      }

      // 2. Import each supported item into its mirrored module.
      for (const m of chosen) {
        const mid = mapping.get(m.canvas_id);
        if (mid == null) continue;
        for (const it of supportedItems(m)) {
          if (it.type === "File" && it.content_id != null)
            await step(it.title, () =>
              api.post(`/api/canvas/modules/${mid}/import`, {
                file_id: it.content_id,
                ai_included: true,
                extract_text: true,
              }),
            );
          else if (it.type === "Page" && it.page_url)
            await step(it.title, () =>
              api.post(`/api/canvas/modules/${mid}/import-page`, {
                canvas_course_id: Number(cid),
                page_url: it.page_url,
              }),
            );
          else if (it.type === "ExternalUrl" && it.external_url)
            await step(it.title, () =>
              api.post(`/api/courses/${course.id}/links`, {
                module_id: mid,
                canvas_item_id: it.canvas_item_id,
                title: it.title,
                url: it.external_url,
              }),
            );
          else if (it.type === "Discussion" && it.content_id != null)
            await step(it.title, () =>
              api.post(`/api/canvas/modules/${mid}/import-discussion`, {
                canvas_course_id: Number(cid),
                topic_id: it.content_id,
              }),
            );
        }
      }

      // 3. Standalone pages/discussions → the hidden "Course files" module.
      let generalId: number | null = null;
      const general = async () => {
        if (generalId == null) {
          const c = await api.post<{ module_id: number }>(
            `/api/courses/${course.id}/course-files-module`,
          );
          generalId = c.module_id;
        }
        return generalId;
      };
      for (const p of s.pages)
        if (selPages.has(p.url))
          await step(p.title, async () =>
            api.post(`/api/canvas/modules/${await general()}/import-page`, {
              canvas_course_id: Number(cid),
              page_url: p.url,
            }),
          );
      for (const d of s.discussions)
        if (selDiscs.has(d.id))
          await step(d.title, async () =>
            api.post(`/api/canvas/modules/${await general()}/import-discussion`, {
              canvas_course_id: Number(cid),
              topic_id: d.id,
            }),
          );
      if (syllabus)
        await step("Syllabus", () =>
          api.post(`/api/canvas/courses/${course.id}/import-syllabus`, {
            canvas_course_id: Number(cid),
          }),
        );

      setFailures(fails);
      queryClient.invalidateQueries({ queryKey: ["modules", String(course.id)] });
      queryClient.invalidateQueries({ queryKey: ["course", String(course.id)] });
      queryClient.invalidateQueries({ queryKey: ["links", String(course.id)] });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
    onSuccess: () => {
      setProgress(null);
      // Keep the dialog open if some items failed so the user can see why.
      if (failures.length === 0) onClose();
    },
    onError: (e) => {
      setProgress(null);
      setError(e instanceof ApiError ? e.message : "Sync failed");
    },
  });

  return (
    <Modal title={`Sync from Canvas — ${course.code}`} onClose={onClose} wide>
      <div className="modal-form">
        {!cid && (
          <p className="error-text">This course isn't linked to Canvas.</p>
        )}
        {structure.isLoading && (
          <p className="gen-hint">
            <Loader2 size={13} className="spin" /> Reading the Canvas course…
          </p>
        )}
        {structure.isError && (
          <p className="error-text">
            {structure.error instanceof ApiError
              ? structure.error.message
              : "Could not reach Canvas"}
          </p>
        )}

        {s && (
          <div className="canvas-sync">
            <p className="gen-hint">
              Selected modules become Manabi modules (topics); their files, pages
              &amp; discussions import as searchable materials, and links become a
              resource list. Re-syncing skips anything already imported.
            </p>

            {s.modules.map((m) => {
              const items = supportedItems(m);
              return (
                <div key={m.canvas_id} className="canvas-sync-mod">
                  <label className="canvas-sync-modhead">
                    <input
                      type="checkbox"
                      checked={selMods.has(m.canvas_id)}
                      disabled={items.length === 0}
                      onChange={() => toggle(setSelMods, m.canvas_id)}
                    />
                    <span className="canvas-sync-modname">{m.name}</span>
                    <span className="canvas-sync-count mono">
                      {items.length} item{items.length === 1 ? "" : "s"}
                    </span>
                  </label>
                  {selMods.has(m.canvas_id) && items.length > 0 && (
                    <ul className="canvas-sync-items">
                      {items.map((it) => {
                        const Icon = ICON[it.type] ?? FileText;
                        return (
                          <li key={it.canvas_item_id}>
                            <Icon size={12} strokeWidth={1.75} /> {it.title}
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              );
            })}

            {s.pages.length > 0 && (
              <details className="canvas-sync-extra">
                <summary>Standalone pages ({s.pages.length})</summary>
                {s.pages.map((p) => (
                  <label key={p.url} className="canvas-sync-extra-row">
                    <input
                      type="checkbox"
                      checked={selPages.has(p.url)}
                      onChange={() => toggle(setSelPages, p.url)}
                    />
                    <ScrollText size={12} strokeWidth={1.75} /> {p.title}
                  </label>
                ))}
              </details>
            )}
            {s.discussions.length > 0 && (
              <details className="canvas-sync-extra">
                <summary>Discussions ({s.discussions.length})</summary>
                {s.discussions.map((d) => (
                  <label key={d.id} className="canvas-sync-extra-row">
                    <input
                      type="checkbox"
                      checked={selDiscs.has(d.id)}
                      onChange={() => toggle(setSelDiscs, d.id)}
                    />
                    <MessagesSquare size={12} strokeWidth={1.75} /> {d.title}
                  </label>
                ))}
              </details>
            )}
            {s.has_syllabus && (
              <label className="canvas-sync-extra-row canvas-sync-syllabus">
                <input
                  type="checkbox"
                  checked={syllabus}
                  onChange={() => setSyllabus((v) => !v)}
                />
                <ScrollText size={12} strokeWidth={1.75} /> Course syllabus → Course
                files
              </label>
            )}
          </div>
        )}

        {progress && (
          <p className="gen-hint">
            <Loader2 size={13} className="spin" /> {progress}
          </p>
        )}
        {failures.length > 0 && (
          <div className="error-text">
            {failures.length} item{failures.length === 1 ? "" : "s"} could not be
            imported:
            <ul>
              {failures.slice(0, 5).map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </div>
        )}
        {error && <p className="error-text">{error}</p>}

        <div className="modal-actions">
          <button className="btn" onClick={onClose}>
            {failures.length > 0 ? "Close" : "Cancel"}
          </button>
          <button
            className="btn btn-primary"
            disabled={totalSelected === 0 || run.isPending}
            onClick={() => run.mutate()}
          >
            <CloudDownload size={15} strokeWidth={1.75} /> Import
            {totalSelected > 0 ? ` (${totalSelected})` : ""}
          </button>
        </div>
      </div>
    </Modal>
  );
}
