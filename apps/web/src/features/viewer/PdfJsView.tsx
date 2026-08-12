import { useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";

// Bundled by Vite (?url) — the classic `new URL(...import.meta.url)` bare
// specifier is flaky under Vite 6; the ?url import is the reliable path.
import workerSrc from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = workerSrc;

/** In-browser PDF render via pdf.js (react-pdf) with a real, selectable text
 * layer. Each page is wrapped with data-page-no so the shared selection popover
 * (highlight + Ask) can anchor a selection to its page — the same flow the
 * text/read modes use, now working directly on the rendered PDF. */
export function PdfJsView({ documentId }: { documentId: string }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [numPages, setNumPages] = useState(0);
  // A scan has no text layer — nothing to select. Detect it from page 1 so we
  // can point the user at the OCR-backed Text/Read views for highlighting.
  const [scanned, setScanned] = useState<boolean | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () =>
      setWidth(Math.min(Math.max(el.clientWidth - 24, 240), 900));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Same-origin GET; withCredentials so the session cookie rides along.
  const file = useMemo(
    () => ({
      url: `/api/documents/${documentId}/original?inline=1`,
      withCredentials: true,
    }),
    [documentId],
  );

  return (
    <div className="viewer-pdfjs" ref={wrapRef}>
      {scanned === true && (
        <p className="pdfjs-scan-note">
          This PDF is scanned, so its text isn't selectable here. Use the{" "}
          <strong>Text</strong> or <strong>Read</strong> view to highlight and
          ask Steven.
        </p>
      )}
      <Document
        file={file}
        onLoadSuccess={({ numPages: n }) => setNumPages(n)}
        loading={<div className="viewer-splash">Loading PDF…</div>}
        error={
          <div className="viewer-splash">
            Could not render this PDF in the browser.
          </div>
        }
      >
        {width > 0 &&
          Array.from({ length: numPages }, (_, i) => (
            <div className="pdfjs-page" data-page-no={i + 1} key={i}>
              <Page
                pageNumber={i + 1}
                width={width}
                renderTextLayer
                renderAnnotationLayer={false}
                onGetTextSuccess={
                  i === 0
                    ? (data: { items: unknown[] }) =>
                        setScanned((data.items?.length ?? 0) === 0)
                    : undefined
                }
              />
            </div>
          ))}
      </Document>
    </div>
  );
}
