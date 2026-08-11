/** Post-render DOM highlighter shared by the per-page text and the Reader.
 *
 * The old approach ran regexes over the HTML *string*, per tag-segment, so any
 * match that crossed a <b>/<br> never matched, term matches had no word
 * boundaries ("IRRI" lit up inside "irrigated"), and the Reader never ran it at
 * all. This walks the rendered DOM instead: one whitespace-normalized view of
 * the visible text with a per-character map back to (textNode, offset), so
 * matches are found on the *visible* text and wrapped with real Ranges — which
 * naturally span element boundaries.
 */
import { useMemo } from "react";

export interface AnnotationMark {
  id: number;
  quote: string;
  color: string;
  hasNote: boolean;
}

const TERM_CLASS = "term-mark";
const ANNOT_CLASS = "annot";

// Block-level tags across whose boundary a synthetic space is inserted, so a
// term/quote never bleeds across a paragraph or line break (matching the
// visible "foo⏎bar" ≈ "foo bar", not "foobar").
const BLOCK_TAGS = new Set([
  "P", "DIV", "LI", "UL", "OL", "TABLE", "THEAD", "TBODY", "TR", "TD", "TH",
  "H1", "H2", "H3", "H4", "H5", "H6", "PRE", "BLOCKQUOTE", "FIGURE",
  "FIGCAPTION", "HR", "SECTION", "ARTICLE",
]);

const WS = /\s/;

/** ASCII word char — used for a manual boundary check instead of \b or a
 * lookbehind (both are flaky / unsupported on older iOS Safari). */
function isWordChar(ch: string | undefined): boolean {
  return ch != null && /[a-zA-Z0-9]/.test(ch);
}

function normalizeQuery(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

interface CharMap {
  text: string; // whitespace-normalized visible text
  node: (Text | null)[]; // origin text node per char (null = synthetic space)
  off: number[]; // origin offset within that node per char
}

/** Depth-first walk of `root`'s text nodes into one normalized string plus a
 * per-character map back to the DOM. Runs of whitespace collapse to a single
 * space; a synthetic space is inserted across block/<br> boundaries. */
function buildCharMap(root: HTMLElement): CharMap {
  const text: string[] = [];
  const node: (Text | null)[] = [];
  const off: number[] = [];

  const pushSep = () => {
    if (text.length && text[text.length - 1] !== " ") {
      text.push(" ");
      node.push(null);
      off.push(-1);
    }
  };

  const walk = (el: Node) => {
    for (let child = el.firstChild; child; child = child.nextSibling) {
      if (child.nodeType === Node.TEXT_NODE) {
        const t = child as Text;
        const s = t.data;
        let i = 0;
        while (i < s.length) {
          if (WS.test(s[i])) {
            if (text.length && text[text.length - 1] !== " ") {
              text.push(" ");
              node.push(t);
              off.push(i);
            }
            i++;
            while (i < s.length && WS.test(s[i])) i++;
          } else {
            text.push(s[i]);
            node.push(t);
            off.push(i);
            i++;
          }
        }
      } else if (child.nodeType === Node.ELEMENT_NODE) {
        const tag = (child as Element).tagName;
        if (tag === "BR") {
          pushSep();
        } else if (BLOCK_TAGS.has(tag)) {
          pushSep();
          walk(child);
          pushSep();
        } else {
          walk(child); // inline (<b>/<i>/<code>/<mark>…) — no separator
        }
      }
    }
  };

  walk(root);
  return { text: text.join(""), node, off };
}

interface Match {
  start: number;
  end: number;
  annot?: AnnotationMark;
}

/** Remove every highlight this module added and stitch the text back together
 * so a re-apply sees clean text nodes. Safe to call on un-highlighted DOM. */
export function clearHighlights(root: HTMLElement): void {
  const marks = root.querySelectorAll(`mark.${TERM_CLASS}, mark.${ANNOT_CLASS}`);
  if (!marks.length) return;
  marks.forEach((mark) => {
    const parent = mark.parentNode;
    if (!parent) return;
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
    parent.removeChild(mark);
  });
  root.normalize(); // merge the text nodes the marks had split
}

/** Wrap term + annotation matches in <mark>s, in place. Terms are whole-word
 * only; annotations match their (whitespace-normalized) quote's first
 * occurrence and win any overlap with a term. Idempotent (clears first). */
export function applyHighlights(
  root: HTMLElement,
  terms: string[],
  annots: AnnotationMark[],
): void {
  clearHighlights(root);
  const map = buildCharMap(root);
  const hay = map.text;
  if (!hay) return;
  const lower = hay.toLowerCase();
  const matches: Match[] = [];

  // Annotations: normalized substring, first occurrence.
  for (const a of annots) {
    const q = normalizeQuery(a.quote);
    if (q.length < 3) continue;
    const idx = lower.indexOf(q.toLowerCase());
    if (idx >= 0) matches.push({ start: idx, end: idx + q.length, annot: a });
  }
  // Terms: every whole-word occurrence.
  for (const raw of terms) {
    const q = normalizeQuery(raw);
    if (q.length < 3) continue;
    const needle = q.toLowerCase();
    let from = 0;
    for (;;) {
      const idx = lower.indexOf(needle, from);
      if (idx < 0) break;
      const end = idx + needle.length;
      if (!isWordChar(hay[idx - 1]) && !isWordChar(hay[end])) {
        matches.push({ start: idx, end });
      }
      from = idx + 1;
    }
  }
  if (!matches.length) return;

  // Priority for overlap resolution: annotations beat terms, then longer, then
  // earlier. Greedily accept non-overlapping matches in that order.
  matches.sort((a, b) => {
    const aw = a.annot ? 0 : 1;
    const bw = b.annot ? 0 : 1;
    if (aw !== bw) return aw - bw;
    const al = a.end - a.start;
    const bl = b.end - b.start;
    if (al !== bl) return bl - al;
    return a.start - b.start;
  });
  const taken = new Array<boolean>(hay.length).fill(false);
  const accepted: Match[] = [];
  for (const m of matches) {
    let free = true;
    for (let i = m.start; i < m.end; i++) {
      if (taken[i]) {
        free = false;
        break;
      }
    }
    if (!free) continue;
    for (let i = m.start; i < m.end; i++) taken[i] = true;
    accepted.push(m);
  }

  // Apply right-to-left: splitting a text node keeps its left remainder as the
  // original node, so earlier offsets/refs in the map stay valid.
  accepted.sort((a, b) => b.start - a.start);
  for (const m of accepted) {
    const startNode = map.node[m.start];
    const endNode = map.node[m.end - 1];
    if (!startNode || !endNode) continue; // matches never begin/end on a synthetic space
    const range = document.createRange();
    range.setStart(startNode, map.off[m.start]);
    range.setEnd(endNode, map.off[m.end - 1] + 1);
    const mark = document.createElement("mark");
    if (m.annot) {
      mark.className = `${ANNOT_CLASS} annot-${m.annot.color}${
        m.annot.hasNote ? " has-note" : ""
      }`;
      mark.dataset.annot = String(m.annot.id);
    } else {
      mark.className = TERM_CLASS;
    }
    try {
      range.surroundContents(mark);
    } catch {
      // Range crosses element boundaries (a <b>/<i>/<br>): extract + wrap.
      try {
        mark.appendChild(range.extractContents());
        range.insertNode(mark);
      } catch {
        // unmarkable (detached/odd range) — skip this one match
      }
    }
  }
}

/** Pure: return `html` with term + annotation matches wrapped in <mark>s. Runs
 * the DOM highlighter over a detached element and serializes the result, so the
 * marks are part of the HTML React renders — no post-render DOM mutation, and
 * therefore no race with React re-setting innerHTML (which silently dropped
 * highlights on load). Browser-only (uses document). */
export function highlightHtml(
  html: string,
  terms: string[],
  annots: AnnotationMark[],
): string {
  if (!html) return html;
  const container = document.createElement("div");
  container.innerHTML = html;
  applyHighlights(container, terms, annots);
  return container.innerHTML;
}

/** React glue: memoized highlighted HTML for dangerouslySetInnerHTML. */
export function useHighlightedHtml(
  html: string,
  terms: string[] | undefined,
  annots: AnnotationMark[] | undefined,
): string {
  const termKey = (terms ?? []).join("");
  const annotKey = (annots ?? [])
    .map((a) => `${a.id}:${a.color}:${a.hasNote ? 1 : 0}:${a.quote}`)
    .join("");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useMemo(() => highlightHtml(html, terms ?? [], annots ?? []), [html, termKey, annotKey]);
}

/** How many of the given terms appear anywhere in the document text. */
export function countTermsPresent(fullText: string, terms: string[]): number {
  const lower = fullText.toLowerCase();
  return terms.filter((t) => lower.includes(t.toLowerCase())).length;
}
