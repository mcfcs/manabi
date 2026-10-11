/** Highlight the word Steven is saying, in whatever text the reader shows.
 *
 * The page text is the extracted HTML; a narration segment's `text` is the
 * same words joined from those elements. Words are matched by a normalised
 * form (letters and digits only), so markup, punctuation and line breaks in
 * between don't matter. Painting uses the CSS Custom Highlight API — no DOM
 * is rewritten, so selections, annotations and search marks are untouched.
 * Browsers without it (iOS < 17.2) simply get no highlight. */

export interface WordRange {
  range: Range;
  norm: string;
}

export const norm = (s: string) => s.toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");

const cache = new WeakMap<Element, { key: string; words: WordRange[] }>();

export function wordRanges(root: Element): WordRange[] {
  const key = String(root.textContent?.length ?? 0);
  const hit = cache.get(root);
  if (hit && hit.key === key) return hit.words;
  const words: WordRange[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.textContent ?? "";
    for (const m of text.matchAll(/\S+/g)) {
      const n = norm(m[0]);
      if (!n) continue;
      const range = document.createRange();
      range.setStart(node, m.index ?? 0);
      range.setEnd(node, (m.index ?? 0) + m[0].length);
      words.push({ range, norm: n });
    }
  }
  cache.set(root, { key, words });
  return words;
}

/** Index in `words` where the segment's tokens begin: the first place its
 * opening words (up to 6) line up, allowing one mismatch for OCR noise. */
export function locate(words: WordRange[], tokens: string[]): number {
  const want = tokens.map(norm).filter(Boolean).slice(0, 6);
  if (!want.length) return -1;
  for (let i = 0; i + want.length <= words.length; i++) {
    let miss = 0;
    for (let k = 0; k < want.length && miss <= 1; k++) {
      if (words[i + k].norm !== want[k]) miss++;
    }
    if (miss <= (want.length > 3 ? 1 : 0)) return i;
  }
  return -1;
}

/** The DOM word for segment token `index`, counting only tokens that have a
 * normalised form (a lone "—" in the segment has no word in the page). */
export function wordFor(
  words: WordRange[],
  start: number,
  tokens: string[],
  index: number,
): WordRange | null {
  let k = start;
  for (let t = 0; t < index; t++) if (norm(tokens[t])) k++;
  return words[k] ?? null;
}

const SUPPORTED = typeof CSS !== "undefined" && "highlights" in CSS;

export function paint(word: Range | null, paragraph: Range | null): void {
  if (!SUPPORTED) return;
  const reg = (CSS as unknown as { highlights: Map<string, unknown> }).highlights;
  const H = (window as unknown as { Highlight: new (...r: Range[]) => unknown }).Highlight;
  if (word) reg.set("narration-word", new H(word));
  else reg.delete("narration-word");
  if (paragraph) reg.set("narration-paragraph", new H(paragraph));
  else reg.delete("narration-paragraph");
}

/** Start ms per token: the recorded timings, or — before a recording is
 * aligned — an estimate spread over the clip by token length. */
export function tokenStarts(tokens: string[], wordTimes: number[] | null, durationMs: number) {
  if (wordTimes && wordTimes.length === tokens.length) return wordTimes;
  const total = tokens.reduce((s, t) => s + Math.max(1, t.length), 0) || 1;
  let acc = 0;
  return tokens.map((t) => {
    const at = Math.round((acc / total) * durationMs);
    acc += Math.max(1, t.length);
    return at;
  });
}

/** The token being spoken at `ms`. */
export function activeToken(starts: number[], ms: number): number {
  let lo = 0;
  let hi = starts.length - 1;
  let ans = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (starts[mid] <= ms) {
      ans = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return ans;
}
