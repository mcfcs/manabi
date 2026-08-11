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
  const n = hay.length;

  // Per-character coverage. Overlapping annotations are NOT dropped — a char in
  // two highlights records both, so the flattened segments below render the
  // overlap as its own mark carrying both ids (click → pick which to note).
  const annotAt: (AnnotationMark[] | null)[] = new Array(n).fill(null);
  const termAt = new Uint8Array(n);

  // Annotations: normalized substring, first occurrence.
  for (const a of annots) {
    const q = normalizeQuery(a.quote);
    if (q.length < 3) continue;
    const idx = lower.indexOf(q.toLowerCase());
    if (idx < 0) continue;
    for (let i = idx; i < idx + q.length; i++) (annotAt[i] ??= []).push(a);
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
        for (let i = idx; i < end; i++) termAt[i] = 1;
      }
      from = idx + 1;
    }
  }

  // Flatten into maximal segments with a constant cover key. Annotations win a
  // char over a term (annotated text renders as the annotation, not the term);
  // a char under two annotations becomes one segment tagged with both.
  const keyAt = (i: number): string => {
    const a = annotAt[i];
    if (a && a.length)
      return "a" + a.map((x) => x.id).sort((p, q) => p - q).join(",");
    return termAt[i] ? "t" : "";
  };

  interface Seg {
    start: number;
    end: number;
    annots: AnnotationMark[] | null;
  }
  const segs: Seg[] = [];
  let i = 0;
  while (i < n) {
    const k = keyAt(i);
    if (!k) {
      i++;
      continue;
    }
    let j = i + 1;
    while (j < n && keyAt(j) === k) j++;
    segs.push({ start: i, end: j, annots: k[0] === "a" ? annotAt[i] : null });
    i = j;
  }
  if (!segs.length) return;

  // Apply right-to-left: splitting a text node keeps its left remainder as the
  // original node, so earlier offsets/refs in the map stay valid. Segments never
  // overlap (they tile), so this is safe even for stacked highlights.
  segs.sort((a, b) => b.start - a.start);
  for (const s of segs) {
    const startNode = map.node[s.start];
    const endNode = map.node[s.end - 1];
    if (!startNode || !endNode) continue; // never begins/ends on a synthetic space
    const range = document.createRange();
    range.setStart(startNode, map.off[s.start]);
    range.setEnd(endNode, map.off[s.end - 1] + 1);
    const mark = document.createElement("mark");
    if (s.annots && s.annots.length) {
      const top = s.annots.reduce((a, b) => (b.id > a.id ? b : a)); // newest on top
      const multi = s.annots.length > 1;
      mark.className =
        `${ANNOT_CLASS} annot-${top.color}` +
        (multi ? " annot-multi" : "") +
        (s.annots.some((a) => a.hasNote) ? " has-note" : "");
      mark.dataset.annotIds = s.annots.map((a) => a.id).join(",");
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
        // unmarkable (detached/odd range) — skip this one segment
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
