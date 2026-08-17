import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Highlighter, NotebookPen, Sparkles, Trash2, X } from "lucide-react";
import { type RefObject, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { api, type AnnotationOut } from "../../lib/api";
import "./viewer.css"; // annot-popover / annot-editor / swatch / mark styles

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

/** Container-level text-selection → popover, mouse + touch (iOS never fires
 * onMouseUp for a long-press selection). Tracks a valid in-container selection
 * via `selectionchange` (debounced) and presents on pointerup/touchend after
 * the touch settles. Shared by the document viewer and the summary: pageNo comes
 * from the nearest [data-page-no] ancestor, falling back to `visiblePage` (0 for
 * non-paged text like the summary). */
export function useSelectionPopover({
  containerRef,
  onSelect,
  visiblePage = 0,
}: {
  containerRef: RefObject<HTMLElement | null>;
  onSelect: (sel: PendingSelection) => void;
  visiblePage?: number;
}) {
  const pending = useRef<PendingSelection | null>(null);
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    let debounce: number | undefined;

    const capture = () => {
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0 || sel.isCollapsed) {
        pending.current = null;
        return;
      }
      const range = sel.getRangeAt(0);
      if (!container.contains(range.commonAncestorContainer)) {
        pending.current = null;
        return;
      }
      const text = sel.toString().replace(/\s+/g, " ").trim();
      if (text.length < 3) {
        pending.current = null;
        return;
      }
      let pageNo = visiblePage;
      const start = range.startContainer;
      const el =
        start.nodeType === Node.ELEMENT_NODE
          ? (start as Element)
          : start.parentElement;
      const pn = el?.closest("[data-page-no]")?.getAttribute("data-page-no");
      if (pn) pageNo = Number(pn);

      const rect = range.getBoundingClientRect();
      const POP_W = 236;
      // Centre under the selection midpoint (viewport coords; the popover is
      // portalled to <body>, so `fixed` is viewport-relative).
      const centerX = (rect.left + rect.right) / 2;
      pending.current = {
        quote: text.slice(0, 2000),
        pageNo,
        x: Math.max(8, Math.min(centerX - POP_W / 2, window.innerWidth - POP_W - 8)),
        y:
          rect.bottom + 8 + 52 > window.innerHeight
            ? Math.max(8, rect.top - 52)
            : rect.bottom + 8,
      };
    };

    const onSelectionChange = () => {
      window.clearTimeout(debounce);
      debounce = window.setTimeout(capture, 150);
    };
    const finalize = () => {
      window.clearTimeout(debounce);
      // Defer so the browser finalizes the selection after the touch/click ends.
      window.setTimeout(() => {
        capture();
        if (pending.current) onSelect(pending.current);
      }, 0);
    };

    document.addEventListener("selectionchange", onSelectionChange);
    container.addEventListener("pointerup", finalize);
    container.addEventListener("touchend", finalize);
    return () => {
      window.clearTimeout(debounce);
      document.removeEventListener("selectionchange", onSelectionChange);
      container.removeEventListener("pointerup", finalize);
      container.removeEventListener("touchend", finalize);
    };
  }, [containerRef, onSelect, visiblePage]);
}

/** Floating popover shown right after the user selects text. */
export function SelectionPopover({
  selection,
  onHighlight,
  onDismiss,
  onAsk,
  allowNote = true,
}: {
  selection: PendingSelection;
  onHighlight: (color: string, note?: string) => void;
  onDismiss: () => void;
  onAsk?: () => void;
  // Hide the note-form affordance (notes highlight is color-only — the note IS
  // the user's own writing, so a per-highlight sticky note is redundant).
  allowNote?: boolean;
}) {
  const [noting, setNoting] = useState(false);
  const [note, setNote] = useState("");
  // Portalled to <body> so position:fixed is viewport-relative — otherwise a
  // transformed ancestor (the routed content area beside the sidebar) becomes
  // the containing block and the popover lands far to the right of the text.
  return createPortal(
    <div
      className="annot-popover"
      style={{ left: selection.x, top: selection.y }}
      // pointerdown (not mousedown) so touch taps on the popover don't fall
      // through to the page and collapse the selection first.
      onPointerDown={(e) => e.stopPropagation()}
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
                onPointerDown={(e) => {
                  e.preventDefault();
                  onHighlight(c, note);
                }}
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
              // pointerdown + preventDefault: acts before the touch/click
              // collapses the selection, so the highlight actually applies.
              onPointerDown={(e) => {
                e.preventDefault();
                onHighlight(c);
              }}
              aria-label={`Highlight ${c}`}
            />
          ))}
          {allowNote && (
            <button
              className="icon-btn"
              onPointerDown={(e) => {
                e.preventDefault();
                setNoting(true);
              }}
              aria-label="Highlight with note"
              title="Highlight + note"
            >
              <NotebookPen size={15} strokeWidth={1.5} />
            </button>
          )}
          {onAsk && (
            <>
              <span className="annot-popover-sep" />
              <button
                className="annot-ask"
                onPointerDown={(e) => {
                  e.preventDefault();
                  onAsk();
                }}
                title="Ask about this passage"
              >
                <Sparkles size={13} strokeWidth={1.75} /> Ask
              </button>
            </>
          )}
          <span className="annot-popover-sep" />
          <button
            className="icon-btn"
            onPointerDown={(e) => {
              e.preventDefault();
              onDismiss();
            }}
            aria-label="Close"
            title="Close"
          >
            <X size={14} strokeWidth={1.5} />
          </button>
        </div>
      )}
    </div>,
    document.body,
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

/** Shown when a click lands on overlapping highlights — pick which one to
 * open/note. Positioned at the click; a backdrop dismisses it. */
export function AnnotationPicker({
  annotations,
  x,
  y,
  onPick,
  onClose,
}: {
  annotations: AnnotationOut[];
  x: number;
  y: number;
  onPick: (id: number) => void;
  onClose: () => void;
}) {
  const left = Math.max(8, Math.min(x, window.innerWidth - 248));
  const top = Math.min(y + 8, window.innerHeight - 40 - annotations.length * 40);
  return (
    <>
      <div className="annot-picker-backdrop" onClick={onClose} />
      <div className="annot-picker" style={{ left, top: Math.max(8, top) }}>
        <div className="annot-picker-head">Which highlight?</div>
        {annotations.map((a) => (
          <button
            key={a.id}
            className="annot-picker-item"
            onClick={() => onPick(a.id)}
          >
            <span className={`annot-item-dot annot-${a.color}`} />
            <span className="annot-picker-quote">"{a.quote.slice(0, 44)}"</span>
            {a.note && <NotebookPen size={12} strokeWidth={1.5} />}
          </button>
        ))}
      </div>
    </>
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
