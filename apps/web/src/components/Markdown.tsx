import DOMPurify from "dompurify";
import { marked } from "marked";
import { useMemo } from "react";

/** Render a small subset of Markdown (bold, italics, lists, code, headings)
 * as sanitized HTML. Used for AI-authored fragments that carry markdown —
 * e.g. the lecture "On the board" panel — which were previously shown raw,
 * so asterisks and dashes leaked to the screen. GFM off; newlines → <br>. */
export function Markdown({
  children,
  className,
}: {
  children: string;
  className?: string;
}) {
  const html = useMemo(() => {
    const raw = marked.parse(children ?? "", {
      breaks: true,
      gfm: false,
      async: false,
    }) as string;
    return DOMPurify.sanitize(raw);
  }, [children]);
  return (
    <div
      className={`md${className ? ` ${className}` : ""}`}
      // Sanitized above; input is AI text derived from the user's own materials.
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
