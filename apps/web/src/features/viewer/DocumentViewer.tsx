import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  LayoutGrid,
  MessageSquareText,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, type DocumentDetail, type ModuleDetail } from "../../lib/api";
import "./viewer.css";

export function DocumentViewer() {
  const { documentId } = useParams({ from: "/documents/$documentId" });
  const { page } = useSearch({ from: "/documents/$documentId" });
  const navigate = useNavigate();
  const [showGrid, setShowGrid] = useState(false);
  const [showNotes, setShowNotes] = useState(false);
  const touchStartX = useRef<number | null>(null);

  const doc = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => api.get<DocumentDetail>(`/api/documents/${documentId}`),
  });

  const module = useQuery({
    queryKey: ["module", String(doc.data?.module_id)],
    queryFn: () => api.get<ModuleDetail>(`/api/modules/${doc.data!.module_id}`),
    enabled: doc.data != null,
  });

  const total = doc.data?.pages.length ?? 0;
  const current = doc.data?.pages.find((p) => p.page_no === page);
  const isSlides = doc.data?.kind === "pptx";

  function goTo(n: number) {
    if (n < 1 || n > total) return;
    navigate({
      to: "/documents/$documentId",
      params: { documentId },
      search: { page: n },
      replace: true,
    });
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") goTo(page + 1);
      if (e.key === "ArrowLeft") goTo(page - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, total]);

  if (doc.isLoading) return <div className="viewer-splash">Loading…</div>;
  if (doc.isError || !doc.data)
    return <div className="viewer-splash">Could not load document.</div>;

  return (
    <div className="viewer">
      <header className="viewer-head">
        <Link
          to="/courses/$courseId/modules/$moduleId"
          params={{
            courseId: String(module.data?.course_id ?? doc.data.module_id),
            moduleId: String(doc.data.module_id),
          }}
          search={{ tab: "materials" }}
          className="viewer-back"
        >
          <ChevronLeft size={16} strokeWidth={1.5} /> Back
        </Link>
        <span className="viewer-title" title={doc.data.filename}>
          {doc.data.filename}
        </span>
        <div className="viewer-tools">
          {isSlides && current?.speaker_notes && (
            <button
              className={`icon-btn${showNotes ? " active" : ""}`}
              onClick={() => setShowNotes((v) => !v)}
              aria-label="Speaker notes"
            >
              <MessageSquareText size={17} strokeWidth={1.5} />
            </button>
          )}
          <button
            className={`icon-btn${showGrid ? " active" : ""}`}
            onClick={() => setShowGrid((v) => !v)}
            aria-label="All pages"
          >
            <LayoutGrid size={17} strokeWidth={1.5} />
          </button>
          <a
            className="icon-btn"
            href={`/api/documents/${documentId}/original`}
            aria-label="Download original"
          >
            <Download size={17} strokeWidth={1.5} />
          </a>
        </div>
      </header>

      {showGrid ? (
        <div className="viewer-grid">
          {doc.data.pages.map((p) => (
            <button
              key={p.page_no}
              className={`grid-cell${p.page_no === page ? " current" : ""}`}
              onClick={() => {
                goTo(p.page_no);
                setShowGrid(false);
              }}
            >
              {p.has_render ? (
                <img
                  src={`/api/documents/${documentId}/pages/${p.page_no}/thumb`}
                  alt={`Page ${p.page_no}`}
                  loading="lazy"
                />
              ) : (
                <span className="grid-cell-text">{p.title ?? `Page ${p.page_no}`}</span>
              )}
              <span className="grid-cell-no">{p.page_no}</span>
            </button>
          ))}
        </div>
      ) : (
        <div
          className="viewer-stage"
          onTouchStart={(e) => (touchStartX.current = e.touches[0].clientX)}
          onTouchEnd={(e) => {
            if (touchStartX.current === null) return;
            const dx = e.changedTouches[0].clientX - touchStartX.current;
            if (Math.abs(dx) > 60) goTo(page + (dx < 0 ? 1 : -1));
            touchStartX.current = null;
          }}
        >
          {current?.has_render ? (
            <img
              className="viewer-page"
              src={`/api/documents/${documentId}/pages/${page}/render`}
              alt={`${isSlides ? "Slide" : "Page"} ${page}`}
            />
          ) : (
            <div className="viewer-text-fallback">
              <h2>{current?.title ?? `${isSlides ? "Slide" : "Page"} ${page}`}</h2>
              <p className="viewer-fallback-hint">
                No visual render available for this {isSlides ? "slide" : "page"}.
              </p>
            </div>
          )}
        </div>
      )}

      {showNotes && current?.speaker_notes && !showGrid && (
        <aside className="notes-drawer">
          <header>
            <span>Speaker notes — slide {page}</span>
            <button className="icon-btn" onClick={() => setShowNotes(false)}>
              <X size={15} strokeWidth={1.5} />
            </button>
          </header>
          <p>{current.speaker_notes}</p>
        </aside>
      )}

      {!showGrid && (
        <footer className="viewer-nav">
          <button
            className="icon-btn"
            disabled={page <= 1}
            onClick={() => goTo(page - 1)}
            aria-label="Previous"
          >
            <ChevronLeft size={18} strokeWidth={1.5} />
          </button>
          <form
            className="page-jump"
            onSubmit={(e) => {
              e.preventDefault();
              const n = Number(new FormData(e.currentTarget).get("n"));
              if (n) goTo(n);
            }}
          >
            <input
              name="n"
              className="page-input mono"
              key={page}
              defaultValue={page}
              inputMode="numeric"
              aria-label="Page number"
            />
            <span className="page-total mono">/ {total}</span>
          </form>
          <button
            className="icon-btn"
            disabled={page >= total}
            onClick={() => goTo(page + 1)}
            aria-label="Next"
          >
            <ChevronRight size={18} strokeWidth={1.5} />
          </button>
        </footer>
      )}
    </div>
  );
}
