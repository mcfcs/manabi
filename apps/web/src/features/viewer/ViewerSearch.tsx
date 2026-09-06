import { ChevronDown, ChevronUp, Search, X } from "lucide-react";
import { useEffect, useRef } from "react";

/** Find-in-document bar for the extracted text. Enter / ↓ → next match,
 * Shift+Enter / ↑ → previous, Escape → close. `focusTick` bumps focus the
 * input again (Ctrl/⌘+F while already open). */
export function ViewerSearch({
  query,
  onQuery,
  total,
  index,
  onIndex,
  onClose,
  focusTick,
  ready,
}: {
  query: string;
  onQuery: (q: string) => void;
  total: number;
  index: number;
  onIndex: (i: number) => void;
  onClose: () => void;
  focusTick: number;
  ready: boolean; // false while the text being searched is still loading
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [focusTick]);

  const step = (delta: number) => {
    if (total === 0) return;
    onIndex((index + delta + total) % total);
  };
  const active = query.trim().length >= 2;

  return (
    <div className="viewer-search" role="search">
      <Search size={15} strokeWidth={1.75} className="viewer-search-icon" />
      <input
        ref={inputRef}
        className="viewer-search-input"
        type="search"
        placeholder="Find in extracted text…"
        value={query}
        onChange={(e) => onQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === "ArrowDown") {
            e.preventDefault();
            step(e.shiftKey && e.key === "Enter" ? -1 : 1);
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            step(-1);
          } else if (e.key === "Escape") {
            e.preventDefault();
            onClose();
          }
        }}
        aria-label="Find in extracted text"
        autoComplete="off"
        spellCheck={false}
      />
      <span className="viewer-search-count mono" aria-live="polite">
        {!active ? "" : !ready ? "…" : total === 0 ? "No matches" : `${index + 1} of ${total}`}
      </span>
      <button
        className="icon-btn"
        onClick={() => step(-1)}
        disabled={total === 0}
        aria-label="Previous match"
        title="Previous match (Shift+Enter)"
      >
        <ChevronUp size={16} strokeWidth={1.75} />
      </button>
      <button
        className="icon-btn"
        onClick={() => step(1)}
        disabled={total === 0}
        aria-label="Next match"
        title="Next match (Enter)"
      >
        <ChevronDown size={16} strokeWidth={1.75} />
      </button>
      <button className="icon-btn" onClick={onClose} aria-label="Close search" title="Close (Esc)">
        <X size={16} strokeWidth={1.75} />
      </button>
    </div>
  );
}
