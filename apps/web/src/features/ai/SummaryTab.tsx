import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, History, ListPlus, PenLine, Search, Trash2, X } from "lucide-react";
import { type MouseEvent as ReactMouseEvent, useRef, useState } from "react";
import { createPortal } from "react-dom";

import {
  api,
  ApiError,
  type ArtifactVersion,
  type ChatThreadOut,
  type JobRef,
  type KeyTerm,
  type SummaryHighlightOut,
  type SummaryOut,
} from "../../lib/api";
import { type AnnotationMark, highlightHtml } from "../../lib/highlight";
import { ChatPanel } from "../chat/ChatPanel";
import {
  AnnotationEditor,
  type PendingSelection,
  SelectionPopover,
  useSelectionPopover,
} from "../viewer/annotations";
import {
  AiOfflineBanner,
  CitationPill,
  JobProgress,
  StalenessBadge,
  useAiOnline,
  useGenerationJob,
} from "./common";
import "./summary.css";

/** Persistent, artifact-anchored summary highlights (the summary analogue of
 * useAnnotations). */
function useSummaryHighlights(artifactId: number | undefined) {
  const queryClient = useQueryClient();
  const key = ["summary-highlights", artifactId];
  const list = useQuery({
    queryKey: key,
    queryFn: () =>
      api.get<SummaryHighlightOut[]>(`/api/artifacts/${artifactId}/highlights`),
    enabled: artifactId != null,
  });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: key });
  const create = useMutation({
    mutationFn: (body: { quote: string; note?: string; color?: string }) =>
      api.post(`/api/artifacts/${artifactId}/highlights`, body),
    onSuccess: invalidate,
  });
  const update = useMutation({
    mutationFn: ({ id, ...body }: { id: number; note?: string; color?: string }) =>
      api.patch(`/api/summary-highlights/${id}`, body),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/api/summary-highlights/${id}`),
    onSuccess: invalidate,
  });
  return { list, create, update, remove };
}

const _ESC: Record<string, string> = {
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
};
const escapeHtml = (s: string) => s.replace(/[&<>"']/g, (c) => _ESC[c]);

function SummaryBody({
  s,
  editing,
  edits,
  onBlockChange,
  onTitleChange,
  marks,
}: {
  s: SummaryOut;
  editing: boolean;
  edits: { title: string; blocks: string[] }[];
  onBlockChange: (si: number, bi: number, text: string) => void;
  onTitleChange: (si: number, text: string) => void;
  marks: AnnotationMark[];
}) {
  // Sidebar jump-nav: Overview → per-section summaries → People → Key terms →
  // Acronyms. Only surface a section when it has content.
  const nav: { id: string; label: string }[] = [];
  if (s.overview) nav.push({ id: "sum-overview", label: "Overview" });
  s.sections.forEach((sec, si) =>
    nav.push({ id: `sum-sec-${si}`, label: sec.title || `Section ${si + 1}` }),
  );
  if (s.people?.length) nav.push({ id: "sum-people", label: "People" });
  if (s.key_terms.length) nav.push({ id: "sum-terms", label: "Key terms" });
  if (s.acronyms.length) nav.push({ id: "sum-acronyms", label: "Acronyms" });

  const jump = (id: string) =>
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });

  // Plain prose → sanitized HTML with saved highlights baked in (reuses the
  // document highlighter). Each highlight's quote is re-found in this text.
  const marked = (textStr: string) => ({
    __html: highlightHtml(escapeHtml(textStr), [], marks),
  });

  return (
    <div className="summary-layout">
      <nav className="summary-nav" aria-label="Summary sections">
        {nav.map((n) => (
          <button
            key={n.id}
            className="summary-nav-item"
            onClick={() => jump(n.id)}
          >
            {n.label}
          </button>
        ))}
      </nav>

      <article className="summary-body">
        {s.overview && (
          <section id="sum-overview" className="summary-overview">
            <h2>Overview</h2>
            <p dangerouslySetInnerHTML={marked(s.overview)} />
          </section>
        )}

        {s.sections.map((section, si) => (
          <section id={`sum-sec-${si}`} key={si}>
            {editing ? (
              <input
                className="input summary-edit-title"
                value={edits[si]?.title ?? section.title}
                onChange={(e) => onTitleChange(si, e.target.value)}
                aria-label={`Section ${si + 1} title`}
              />
            ) : (
              <h2>
                {si + 1}. {section.title}
              </h2>
            )}
            {section.blocks.map((block, bi) => (
              <div className="summary-block" key={bi}>
                {editing ? (
                  <textarea
                    className="input summary-edit-block"
                    value={edits[si]?.blocks[bi] ?? block.text}
                    onChange={(e) => onBlockChange(si, bi, e.target.value)}
                    rows={Math.max(2, Math.ceil((edits[si]?.blocks[bi] ?? block.text).length / 80))}
                  />
                ) : (
                  <p dangerouslySetInnerHTML={marked(block.text)} />
                )}
                <span className="summary-cites">
                  {block.edited && !editing && (
                    <span className="badge stale">edited</span>
                  )}
                  {(s.citations[`s${si}:b${bi}`] ?? []).map((c) => (
                    <CitationPill key={c.id} citation={c} />
                  ))}
                </span>
              </div>
            ))}
          </section>
        ))}

        {s.people?.length > 0 && (
          <section id="sum-people">
            <h2>People</h2>
            <dl className="key-terms">
              {s.people.map((p, i) => (
                <div className="key-term" key={i}>
                  <dt>{p.name}</dt>
                  <dd>
                    {p.description}
                    <span className="summary-cites">
                      {(s.citations[`pep:${i}`] ?? []).map((c) => (
                        <CitationPill key={c.id} citation={c} />
                      ))}
                    </span>
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        )}

        {s.key_terms.length > 0 && (
          <section id="sum-terms">
            <h2>Key terms</h2>
            <dl className="key-terms">
              {s.key_terms.map((t, i) => (
                <div className="key-term" key={i}>
                  <dt>{t.term}</dt>
                  <dd>
                    {t.definition}
                    <span className="summary-cites">
                      {t.user_added && <span className="badge stale">added by you</span>}
                      {t.found_by_ai && (
                        <span className="badge fresh">found on request</span>
                      )}
                      {(s.citations[`kt:${i}`] ?? []).map((c) => (
                        <CitationPill key={c.id} citation={c} />
                      ))}
                    </span>
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        )}

        {s.acronyms.length > 0 && (
          <section id="sum-acronyms">
            <h2>Acronyms</h2>
            <div className="acronym-grid">
              {s.acronyms.map((a, i) => (
                <div className="acronym" key={i}>
                  <span className="acronym-short">{a.acronym}</span>
                  <span className="acronym-long">
                    {a.meaning}
                    {(s.citations[`ac:${i}`] ?? []).slice(0, 1).map((c) => (
                      <CitationPill key={c.id} citation={c} />
                    ))}
                  </span>
                </div>
              ))}
            </div>
          </section>
        )}
      </article>
    </div>
  );
}

function TermsManager({
  summary,
  moduleId,
  onClose,
}: {
  summary: SummaryOut;
  moduleId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [terms, setTerms] = useState<KeyTerm[]>(summary.key_terms);
  const [findInput, setFindInput] = useState("");
  const [findError, setFindError] = useState<string | null>(null);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["summary", moduleId] });
  };

  const save = useMutation({
    mutationFn: () =>
      api.patch(`/api/artifacts/${summary.artifact_id}/terms`, {
        key_terms: terms.map((t) => ({
          term: t.term,
          definition: t.definition,
          user_added: t.user_added ?? false,
        })),
      }),
    onSuccess: () => {
      invalidate();
      onClose();
    },
  });

  const find = useMutation({
    mutationFn: (term: string) =>
      api.post<JobRef>(`/api/artifacts/${summary.artifact_id}/terms/find`, { term }),
    onSuccess: () => {
      setFindError(null);
      setFindInput("");
      onClose(); // job progress surfaces via active-jobs; summary refreshes on done
    },
    onError: (err) =>
      setFindError(err instanceof ApiError ? err.message : "Request failed"),
  });

  function update(i: number, patch: Partial<KeyTerm>) {
    setTerms((prev) => prev.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  }

  return (
    <div className="terms-manager">
      <h3>Manage key terms</h3>
      <div className="terms-rows">
        {terms.map((t, i) => (
          <div className="terms-row" key={i}>
            <input
              className="input terms-term"
              value={t.term}
              onChange={(e) => update(i, { term: e.target.value, user_added: true })}
            />
            <input
              className="input terms-def"
              value={t.definition}
              onChange={(e) =>
                update(i, { definition: e.target.value, user_added: true })
              }
            />
            <button
              className="icon-btn danger"
              onClick={() => setTerms((prev) => prev.filter((_, j) => j !== i))}
              aria-label="Remove term"
            >
              <Trash2 size={14} strokeWidth={1.5} />
            </button>
          </div>
        ))}
      </div>
      <button
        className="btn"
        onClick={() =>
          setTerms((prev) => [...prev, { term: "", definition: "", user_added: true }])
        }
      >
        <ListPlus size={15} strokeWidth={1.75} /> Add manually
      </button>

      <div className="terms-find">
        <input
          className="input"
          placeholder="Missing term? Let the AI find it in the materials…"
          value={findInput}
          onChange={(e) => setFindInput(e.target.value)}
        />
        <button
          className="btn"
          disabled={!findInput.trim() || find.isPending}
          onClick={() => find.mutate(findInput.trim())}
        >
          <Search size={15} strokeWidth={1.75} /> Find in material
        </button>
      </div>
      {findError && <p className="error-text">{findError}</p>}
      {save.isError && <p className="error-text">{(save.error as Error).message}</p>}

      <div className="modal-actions">
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn btn-primary"
          disabled={save.isPending}
          onClick={() => save.mutate()}
        >
          Save terms
        </button>
      </div>
    </div>
  );
}

export function SummaryTab({ moduleId }: { moduleId: string }) {
  const queryClient = useQueryClient();
  const aiOnline = useAiOnline();
  const [viewingVersion, setViewingVersion] = useState<number | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const summary = useQuery({
    queryKey: ["summary", moduleId],
    queryFn: () => api.get<SummaryOut | null>(`/api/modules/${moduleId}/summary`),
  });

  const versions = useQuery({
    queryKey: ["summary-versions", moduleId],
    queryFn: () =>
      api.get<ArtifactVersion[]>(`/api/modules/${moduleId}/artifacts?type=summary`),
    enabled: showHistory,
  });

  const oldVersion = useQuery({
    queryKey: ["artifact", viewingVersion],
    queryFn: () => api.get<SummaryOut>(`/api/artifacts/${viewingVersion}`),
    enabled: viewingVersion != null,
  });

  const gen = useGenerationJob(moduleId, "generate_summary", () => {
    queryClient.invalidateQueries({ queryKey: ["summary", moduleId] });
    queryClient.invalidateQueries({ queryKey: ["summary-versions", moduleId] });
  });
  const findJob = useGenerationJob(moduleId, "define_term", () => {
    queryClient.invalidateQueries({ queryKey: ["summary", moduleId] });
  });
  const [managingTerms, setManagingTerms] = useState(false);

  const generate = useMutation({
    mutationFn: () =>
      api.post<JobRef>(`/api/modules/${moduleId}/summary/generate`),
    onSuccess: (ref) => gen.start(ref.job_id),
  });

  const s = viewingVersion != null ? oldVersion.data : summary.data;
  const viewingOld = viewingVersion != null && s != null;
  const live = summary.data; // the editable/highlightable latest summary

  // ── Highlights + Ask (latest summary only) ──
  const highlights = useSummaryHighlights(live?.artifact_id);
  const containerRef = useRef<HTMLDivElement>(null);
  const [selection, setSelection] = useState<PendingSelection | null>(null);
  const [discuss, setDiscuss] = useState<ChatThreadOut | null>(null);
  const [editingHl, setEditingHl] = useState<{
    hl: SummaryHighlightOut;
    x: number;
    y: number;
  } | null>(null);
  useSelectionPopover({ containerRef, onSelect: setSelection });

  const marks: AnnotationMark[] = (highlights.list.data ?? []).map((h) => ({
    id: h.id,
    quote: h.quote,
    color: h.color,
    hasNote: !!h.note,
  }));

  const startDiscussion = useMutation({
    mutationFn: (quote: string) =>
      api.post<ChatThreadOut>(`/api/modules/${moduleId}/summary/discuss`, { quote }),
    onSuccess: (thread) => setDiscuss(thread),
  });

  // ── Edit mode (latest summary only) ──
  const [editing, setEditing] = useState(false);
  const [edits, setEdits] = useState<{ title: string; blocks: string[] }[]>([]);
  function startEdit() {
    if (!live) return;
    setEdits(
      live.sections.map((sec) => ({
        title: sec.title,
        blocks: sec.blocks.map((b) => b.text),
      })),
    );
    setEditing(true);
  }
  const saveEdits = useMutation({
    mutationFn: () =>
      api.patch(`/api/artifacts/${live!.artifact_id}/sections`, {
        sections: edits.map((sec) => ({
          title: sec.title,
          blocks: sec.blocks.map((text) => ({ text })),
        })),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["summary", moduleId] });
      setEditing(false);
    },
  });

  // A highlight <mark> click (bubbled to the container) → open its editor.
  const onContainerClick = (e: ReactMouseEvent) => {
    const mark = (e.target as HTMLElement).closest("mark.annot");
    const ids = (mark as HTMLElement | null)?.dataset.annotIds;
    if (!ids) return;
    const hl = (highlights.list.data ?? []).find(
      (h) => h.id === Number(ids.split(",")[0]),
    );
    if (hl) setEditingHl({ hl, x: e.clientX, y: e.clientY });
  };

  return (
    <div className="summary-tab" ref={containerRef} onClick={onContainerClick}>
      {summary.data && (
        <header className="gen-head">
          <StalenessBadge staleness={summary.data.staleness} />
          {summary.data.coverage && (
            <span
              className="badge fresh"
              title="How many source passages this summary cites"
            >
              cites {summary.data.coverage.cited}/{summary.data.coverage.total}{" "}
              passages
            </span>
          )}
          {summary.data.edited_at && (
            <span
              className="badge stale"
              title={`You edited this summary on ${new Date(summary.data.edited_at).toLocaleString()}`}
            >
              edited · {new Date(summary.data.edited_at).toLocaleDateString()}
            </span>
          )}
          <span className="gen-head-meta">
            generated {new Date(summary.data.generated_at).toLocaleString()} ·{" "}
            {summary.data.model_name}
          </span>
          <span className="gen-head-spacer" />
          {editing ? (
            <>
              <button className="btn" onClick={() => setEditing(false)}>
                <X size={15} strokeWidth={1.75} /> Cancel
              </button>
              <button
                className="btn btn-primary"
                onClick={() => saveEdits.mutate()}
                disabled={saveEdits.isPending}
              >
                <Check size={15} strokeWidth={1.75} /> Save edits
              </button>
            </>
          ) : (
            <>
              {!viewingOld && (
                <button className="btn" onClick={startEdit}>
                  <PenLine size={15} strokeWidth={1.75} /> Edit
                </button>
              )}
              <button
                className={`btn${managingTerms ? " active" : ""}`}
                onClick={() => setManagingTerms((v) => !v)}
              >
                <ListPlus size={15} strokeWidth={1.75} /> Terms
              </button>
              <button
                className={`btn${showHistory ? " active" : ""}`}
                onClick={() => {
                  setShowHistory((v) => !v);
                  if (showHistory) setViewingVersion(null);
                }}
              >
                <History size={15} strokeWidth={1.75} /> History
              </button>
              <button
                className="btn btn-primary"
                onClick={() => generate.mutate()}
                disabled={gen.running || generate.isPending}
                title="Your notes guide emphasis — they are never treated as source material"
              >
                <PenLine size={15} strokeWidth={1.75} /> Regenerate
              </button>
            </>
          )}
        </header>
      )}

      {showHistory && versions.data && (
        <div className="version-list">
          {versions.data.map((v) => (
            <button
              key={v.artifact_id}
              className={`version-item${
                (viewingVersion ?? summary.data?.artifact_id) === v.artifact_id
                  ? " current"
                  : ""
              }`}
              onClick={() =>
                setViewingVersion(
                  v.artifact_id === summary.data?.artifact_id ? null : v.artifact_id,
                )
              }
            >
              {new Date(v.generated_at).toLocaleString()} · {v.item_count} blocks ·{" "}
              {v.model_name}
              {v.artifact_id === summary.data?.artifact_id && " (latest)"}
            </button>
          ))}
        </div>
      )}

      {viewingOld && (
        <p className="version-banner">
          Viewing version from {new Date(s!.generated_at).toLocaleString()} —{" "}
          <button className="link-btn" onClick={() => setViewingVersion(null)}>
            back to latest
          </button>
        </p>
      )}

      {managingTerms && summary.data && (
        <TermsManager
          summary={summary.data}
          moduleId={moduleId}
          onClose={() => setManagingTerms(false)}
        />
      )}

      {!aiOnline && (gen.running || !summary.data) && <AiOfflineBanner />}
      {gen.running && <JobProgress job={gen.job} />}
      {findJob.running && <JobProgress job={findJob.job} />}
      {findJob.job?.status === "failed" && (
        <p className="error-text">{findJob.job.error}</p>
      )}
      {gen.job?.status === "failed" && (
        <p className="error-text">Generation failed: {gen.job.error}</p>
      )}
      {generate.isError && (
        <p className="error-text">{(generate.error as Error).message}</p>
      )}

      {!summary.data && !gen.running && summary.isSuccess && (
        <div className="gen-empty">
          <p>
            No summary yet. Manabi will build structured study notes from this
            module's materials — every claim cited back to its source page.
          </p>
          <button
            className="btn btn-primary"
            onClick={() => generate.mutate()}
            disabled={generate.isPending}
          >
            <PenLine size={15} strokeWidth={1.75} /> Generate summary
          </button>
          <p className="gen-hint">
            Your notes guide emphasis — they are never treated as source material.
          </p>
        </div>
      )}

      {s && (
        <SummaryBody
          s={s}
          editing={editing && !viewingOld}
          edits={edits}
          onBlockChange={(si, bi, text) =>
            setEdits((prev) =>
              prev.map((sec, i) =>
                i === si
                  ? { ...sec, blocks: sec.blocks.map((b, j) => (j === bi ? text : b)) }
                  : sec,
              ),
            )
          }
          onTitleChange={(si, text) =>
            setEdits((prev) =>
              prev.map((sec, i) => (i === si ? { ...sec, title: text } : sec)),
            )
          }
          marks={viewingOld ? [] : marks}
        />
      )}

      {selection && !editing && !viewingOld && (
        <SelectionPopover
          selection={selection}
          onHighlight={(color, note) => {
            highlights.create.mutate({ quote: selection.quote, color, note });
            setSelection(null);
            window.getSelection()?.removeAllRanges();
          }}
          onDismiss={() => setSelection(null)}
          onAsk={() => {
            startDiscussion.mutate(selection.quote);
            setSelection(null);
            window.getSelection()?.removeAllRanges();
          }}
        />
      )}

      {editingHl &&
        createPortal(
          <>
            <div className="summary-hl-backdrop" onClick={() => setEditingHl(null)} />
            <div
              className="summary-hl-editor"
              style={{
                left: Math.max(8, Math.min(editingHl.x, window.innerWidth - 320)),
                top: Math.min(editingHl.y + 8, window.innerHeight - 220),
              }}
            >
              <AnnotationEditor
                annotation={{ ...editingHl.hl, page_no: 0 }}
                onSave={(note) => {
                  highlights.update.mutate({ id: editingHl.hl.id, note });
                  setEditingHl(null);
                }}
                onDelete={() => {
                  highlights.remove.mutate(editingHl.hl.id);
                  setEditingHl(null);
                }}
                onClose={() => setEditingHl(null)}
              />
            </div>
          </>,
          document.body,
        )}

      {discuss && (
        <ChatPanel moduleId={moduleId} thread={discuss} onClose={() => setDiscuss(null)} />
      )}
    </div>
  );
}
