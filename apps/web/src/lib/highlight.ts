/** Wrap case-insensitive term matches in <mark>, touching ONLY text segments
 * (never tag internals). html is server-sanitized (b/i/p/br + margin style). */
export function highlightTerms(html: string, terms: string[]): string {
  const usable = terms.filter((t) => t.trim().length > 2);
  if (!usable.length) return html;
  const escaped = usable.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const re = new RegExp(`(${escaped.join("|")})`, "gi");
  return html
    .split(/(<[^>]*>)/g)
    .map((seg) =>
      seg.startsWith("<") ? seg : seg.replace(re, '<mark class="term-mark">$1</mark>'),
    )
    .join("");
}

/** How many of the given terms appear anywhere in the document text. */
export function countTermsPresent(fullText: string, terms: string[]): number {
  const lower = fullText.toLowerCase();
  return terms.filter((t) => lower.includes(t.toLowerCase())).length;
}
