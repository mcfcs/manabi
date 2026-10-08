import DOMPurify from "dompurify";
import { marked } from "marked";
import { useMemo } from "react";

/** Problem statements: GFM on, so single newlines break (marked only honours
 * `breaks` with GFM) — constraints and formats are often one rule per line —
 * and tables render. Sanitized like the shared <Markdown>. */
export function StatementMarkdown({ children, className }: { children: string; className?: string }) {
  const html = useMemo(() => {
    const raw = marked.parse(children ?? "", { gfm: true, breaks: true, async: false }) as string;
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
