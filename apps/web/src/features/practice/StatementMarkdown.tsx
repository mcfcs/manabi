import "katex/dist/katex.min.css";

import DOMPurify from "dompurify";
import katex from "katex";
import { marked } from "marked";
import { useMemo } from "react";

// $…$ and $$…$$ — the generator writes set notation as LaTeX ("$\{0, 1\}$").
// (KaTeX is already in the main bundle via the notes editor.)
const MATH = /\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$/g;

/** Problem statements: GFM on, so single newlines break (marked only honours
 * `breaks` with GFM) — constraints and formats are often one rule per line —
 * and tables render. Math is typeset with KaTeX. Sanitized like the shared
 * <Markdown>. */
export function StatementMarkdown({ children, className }: { children: string; className?: string }) {
  const html = useMemo(() => {
    const blocks: string[] = [];
    // Typeset first and park the result behind a placeholder, so marked
    // never sees (and mangles) TeX backslashes and underscores.
    const prepared = (children ?? "").replace(
      MATH,
      (_m, display: string | undefined, inline: string | undefined) => {
        const tex = (display ?? inline ?? "").trim();
        blocks.push(
          katex.renderToString(tex, { displayMode: display !== undefined, throwOnError: false })
        );
        return `@@MATH${blocks.length - 1}@@`;
      }
    );
    let raw = marked.parse(prepared, { gfm: true, breaks: true, async: false }) as string;
    raw = raw.replace(/@@MATH(\d+)@@/g, (_m, i: string) => blocks[Number(i)] ?? "");
    return DOMPurify.sanitize(raw);
  }, [children]);

  return (
    <div
      className={`md${className ? ` ${className}` : ""}`}
      // Sanitized above.
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
