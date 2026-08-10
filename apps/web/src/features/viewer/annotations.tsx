import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Highlighter, NotebookPen, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";

import { api, type AnnotationOut } from "../../lib/api";

const COLORS = ["yellow", "blue", "green", "red"] as const;

export function useAnnotations(documentId: string) {
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: ["annotations", documentId],
    queryFn: () =>
      api.get<AnnotationOut[]>(`/api/documents/${documentId}/annotations`),
  });
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["annotations", documentId] });

  const create = useMutation({
    mutationFn: (body: {
      page_no: number;
      quote: string;
      note?: string;
      color?: string;
    }) => api.post(`/api/documents/${documentId}/annotations`, body),
    onSuccess: invalidate,
  });
  const update = useMutation({
    mutationFn: ({ id, ...body }: { id: number; note?: string; color?: string }) =>
      api.patch(`/api/annotations/${id}`, body),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/api/annotations/${id}`),
    onSuccess: invalidate,
  });
  return { list, create, update, remove };
}

export interface PendingSelection {
  quote: string;
  pageNo: number;
  x: number;
  y: number;
}

/** Floating popover shown right after the user selects text. */
export function SelectionPopover({
  selection,
  onHighlight,
  onDismiss,
  onAsk,
}: {
  selection: PendingSelection;
  onHighlight: (color: string, note?: string) => void;
  onDismiss: () => void;
  onAsk?: () => void;
}) {
  const [noting, setNoting] = useState(false);
  const [note, setNote] = useState("");
  return (
    <div
      className="annot-popover"
      style={{ left: selection.x, top: selection.y }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      {noting ? (
        <div className="annot-note-form">
          <textarea
            className="input annot-note-input"
            placeholder="Your note…"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            autoFocus
          />
          <div className="annot-popover-row">
            {COLORS.map((c) => (
              <button
                key={c}
                className={`annot-swatch annot-${c}`}
                onClick={() => onHighlight(c, note)}
                aria-label={`Save with ${c} highlight`}
              />
            ))}
            <button className="icon-btn" onClick={onDismiss} aria-label="Cancel">
              <X size={14} strokeWidth={1.5} />
            </button>
          </div>
        </div>
      ) : (
        <div className="annot-popover-row">
          {COLORS.map((c) => (
            <button
              key={c}
              className={`annot-swatch annot-${c}`}
              onClick={() => onHighlight(c)}
              aria-label={`Highlight ${c}`}
            />
          ))}
          <button
            className="icon-btn"
            onClick={() => setNoting(true)}
            aria-label="Highlight with note"
            title="Highlight + note"
          >
            <NotebookPen size={15} strokeWidth={1.5} />
          </button>
          {onAsk && (
            <button
              className="annot-act annot-ask"
              onMouseDown={(e) => {
                e.preventDefault();
                onAsk();
              }}
              title="Ask Steven about this passage"
            >
              Ask Steven
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** Popover for an existing annotation (view/edit note, delete). */
export function AnnotationEditor({
  annotation,
  onSave,
  onDelete,
  onClose,
}: {
  annotation: AnnotationOut;
  onSave: (note: string) => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  const [note, setNote] = useState(annotation.note ?? "");
  useEffect(() => setNote(annotation.note ?? ""), [annotation.id, annotation.note]);
  return (
    <div className="annot-editor">
      <header>
        <Highlighter size={14} strokeWidth={1.5} />
        <span className="annot-editor-quote">"{annotation.quote.slice(0, 60)}…"</span>
        <button className="icon-btn" onClick={onClose} aria-label="Close">
          <X size={14} strokeWidth={1.5} />
        </button>
      </header>
      <textarea
        className="input annot-note-input"
        placeholder="Add a note…"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        rows={3}
      />
      <div className="modal-actions">
        <button className="icon-btn danger" onClick={onDelete} aria-label="Delete">
          <Trash2 size={15} strokeWidth={1.5} />
        </button>
        <button className="btn btn-primary" onClick={() => onSave(note)}>
          Save
        </button>
      </div>
    </div>
  );
}

/** Side list of all annotations in the document with jump links. */
export function AnnotationsPanel({
  annotations,
  onJump,
  onClose,
}: {
  annotations: AnnotationOut[];
  onJump: (a: AnnotationOut) => void;
  onClose: () => void;
}) {
  return (
    <aside className="annot-panel">
      <header>
        <span>Annotations ({annotations.length})</span>
        <button className="icon-btn" onClick={onClose} aria-label="Close">
          <X size={14} strokeWidth={1.5} />
        </button>
      </header>
      {annotations.length === 0 && (
        <p className="annot-panel-empty">
          Select text in the Text view to highlight it and attach notes.
        </p>
      )}
      {annotations.map((a) => (
        <button key={a.id} className="annot-item" onClick={() => onJump(a)}>
          <span className={`annot-item-dot annot-${a.color}`} />
          <span className="annot-item-body">
            <span className="annot-item-quote">"{a.quote.slice(0, 70)}"</span>
            {a.note && <span className="annot-item-note">{a.note}</span>}
            <span className="annot-item-page mono">p. {a.page_no}</span>
          </span>
        </button>
      ))}
    </aside>
  );
}
