import DOMPurify from "dompurify";
import { marked } from "marked";
import { useMemo } from "react";

/** Render a small subset of Markdown (bold, italics, lists, code, headings)
 * as sanitized HTML. Used for AI-authored fragments that carry markdown —
 * e.g. the lecture "On the board" panel — which were previously shown raw,
 * so asterisks and dashes leaked to the screen. GFM off unless `gfm` (quiz
 * prompts carry small data tables); newlines → <br>. */
export function Markdown({
  children,
  className,
  gfm = false,
}: {
  children: string;
  className?: string;
  gfm?: boolean;
}) {
  const html = useMemo(() => {
    const raw = marked.parse(children ?? "", {
      breaks: true,
      gfm,
      async: false,
    }) as string;
    return DOMPurify.sanitize(raw);
  }, [children, gfm]);
  return (
    <div
      className={`md${className ? ` ${className}` : ""}`}
      // Sanitized above; input is AI text derived from the user's own materials.
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
