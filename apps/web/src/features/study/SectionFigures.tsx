import { Link } from "@tanstack/react-router";
import { ExternalLink, X } from "lucide-react";
import { useState } from "react";
import { createPortal } from "react-dom";

import type { SummaryOut } from "../../lib/api";

type Page = { documentId: number; page: number; title: string };

/** The slide/page images a summary section cites. They are the material's
 * own figures (diagrams, code listings, tables), so nothing here can be
 * invented: a picture of page 12 is page 12. */
export function sectionPages(
  summary: SummaryOut | undefined,
  index: number,
  allowedDocs: Set<number> | null,
  limit = 6,
): Page[] {
  if (!summary) return [];
  const seen = new Set<string>();
  const out: Page[] = [];
  for (const [ref, cites] of Object.entries(summary.citations ?? {})) {
    if (!ref.startsWith(`s${index}:`)) continue;
    for (const c of cites) {
      if (c.document_id == null || c.page_start == null) continue;
      if (allowedDocs && !allowedDocs.has(c.document_id)) continue;
      const key = `${c.document_id}:${c.page_start}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ documentId: c.document_id, page: c.page_start, title: c.document_title });
    }
  }
  out.sort((a, b) => a.documentId - b.documentId || a.page - b.page);
  return out.slice(0, limit);
}

export function SectionFigures({ pages }: { pages: Page[] }) {
  const [open, setOpen] = useState<Page | null>(null);
  if (!pages.length) return null;
  return (
    <>
      <div className="sec-figs" aria-label="Slides this section is drawn from">
        {pages.map((p) => (
          <button
            key={`${p.documentId}:${p.page}`}
            type="button"
            className="sec-fig"
            onClick={() => setOpen(p)}
            title={`${p.title}, page ${p.page}`}
          >
            <img
              src={`/api/documents/${p.documentId}/pages/${p.page}/thumb`}
              alt={`${p.title}, page ${p.page}`}
              loading="lazy"
            />
            <span className="sec-fig-cap">p. {p.page}</span>
          </button>
        ))}
      </div>
      {open &&
        createPortal(
          <div className="sec-lightbox" onClick={() => setOpen(null)} role="dialog" aria-label="Slide">
            <div className="sec-lightbox-inner" onClick={(e) => e.stopPropagation()}>
              <div className="sec-lightbox-bar">
                <span>
                  {open.title}, page {open.page}
                </span>
                <Link
                  className="btn btn-sm"
                  to="/documents/$documentId"
                  params={{ documentId: String(open.documentId) }}
                  search={{ page: open.page }}
                >
                  <ExternalLink size={13} strokeWidth={1.75} /> Open in viewer
                </Link>
                <button type="button" className="modal-close" onClick={() => setOpen(null)} aria-label="Close">
                  <X size={18} strokeWidth={1.5} />
                </button>
              </div>
              <img
                src={`/api/documents/${open.documentId}/pages/${open.page}/render`}
                alt={`${open.title}, page ${open.page}`}
              />
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
