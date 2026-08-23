import { useQuery } from "@tanstack/react-query";
import { BookMarked, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, type DocumentOut, type NoteListItem } from "../../lib/api";
import "../chat/chat.css";

/** Material scope picker: which documents and note sections are in scope.
 * Controlled: null arrays = everything of that kind; explicit arrays narrow
 * it. Used by chat threads (persisted per thread) and by card/quiz
 * generation (local config state). */
export function SourcesPicker({
  moduleId,
  documentIds,
  noteIds,
  onChange,
  disabled,
}: {
  moduleId: string;
  documentIds: number[] | null;
  noteIds: number[] | null;
  onChange: (documentIds: number[] | null, noteIds: number[] | null) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const documents = useQuery({
    queryKey: ["documents", moduleId],
    queryFn: () => api.get<DocumentOut[]>(`/api/modules/${moduleId}/documents`),
    enabled: open,
  });
  const notes = useQuery({
    queryKey: ["notes", moduleId],
    queryFn: () => api.get<NoteListItem[]>(`/api/modules/${moduleId}/notes`),
    enabled: open,
  });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  const docIds = (documents.data ?? [])
    .filter((d) => d.ai_included)
    .map((d) => d.id);
  const allNoteIds = (notes.data ?? []).map((n) => n.id);
  const isAll = documentIds === null && noteIds === null;
  const docsSel = new Set(documentIds ?? docIds);
  const notesSel = new Set(noteIds ?? allNoteIds);

  function toggle(kind: "doc" | "note", id: number) {
    const nextDocs = new Set(docsSel);
    const nextNotes = new Set(notesSel);
    const set = kind === "doc" ? nextDocs : nextNotes;
    if (set.has(id)) set.delete(id);
    else set.add(id);
    onChange([...nextDocs], [...nextNotes]);
  }

  const selectedCount = (documentIds?.length ?? 0) + (noteIds?.length ?? 0);

  return (
    <div className="chat-scope" ref={rootRef}>
      <button
        type="button"
        className={`chat-teacher-toggle${!isAll ? " on" : ""}`}
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        title="Choose which materials are in scope"
      >
        <BookMarked size={14} strokeWidth={1.75} />
        Sources: {isAll ? "all materials" : `${selectedCount} selected`}
      </button>
      {open && (
        <div className="chat-scope-pop">
          <label className="chat-scope-row chat-scope-all">
            <input
              type="checkbox"
              checked={isAll}
              onChange={() =>
                isAll ? onChange(docIds, allNoteIds) : onChange(null, null)
              }
            />
            All materials
          </label>
          {(documents.isLoading || notes.isLoading) && (
            <p className="chat-scope-hint">
              <Loader2 size={12} className="spin" /> Loading materials…
            </p>
          )}
          {docIds.length > 0 && <p className="chat-scope-hint">Files</p>}
          {(documents.data ?? [])
            .filter((d) => d.ai_included)
            .map((d) => (
              <label key={d.id} className="chat-scope-row">
                <input
                  type="checkbox"
                  checked={docsSel.has(d.id)}
                  onChange={() => toggle("doc", d.id)}
                />
                <span className="chat-scope-name">{d.filename}</span>
              </label>
            ))}
          {allNoteIds.length > 0 && <p className="chat-scope-hint">Notes</p>}
          {(notes.data ?? []).map((n) => (
            <label key={n.id} className="chat-scope-row">
              <input
                type="checkbox"
                checked={notesSel.has(n.id)}
                onChange={() => toggle("note", n.id)}
              />
              <span className="chat-scope-name">{n.title}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
