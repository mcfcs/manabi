import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  GalleryVertical,
  Highlighter,
  LayoutGrid,
  MessageSquareText,
  Square,
  Type,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  api,
  type DocumentDetail,
  type ModuleDetail,
  type PageOut,
  type RegionOut,
  type SummaryOut,
} from "../../lib/api";
import { countTermsPresent, highlightTerms } from "../../lib/highlight";
import "./viewer.css";

type ViewMode = "single" | "scroll" | "grid";

function loadMode(): ViewMode {
  const saved = localStorage.getItem("manabi-viewer-mode");
  return saved === "single" || saved === "grid" ? saved : "scroll";
}

function PageImage({
  documentId,
  page,
  regions,
  lazy,
}: {
  documentId: string;
  page: PageOut;
  regions: RegionOut[];
  lazy?: boolean;
}) {
  const pageRegions = regions.filter((r) => r.page_no === page.page_no);
  return (
    <span className="viewer-page-wrap">
      <img
        className="viewer-page"
        src={`/api/documents/${documentId}/pages/${page.page_no}/render`}
        alt={`Page ${page.page_no}`}
        loading={lazy ? "lazy" : undefined}
      />
      {pageRegions.map((r, i) => (
        <span
          key={i}
          className="viewer-highlight"
          style={{
            left: `${r.left * 100}%`,
            top: `${r.top * 100}%`,
            width: `${r.width * 100}%`,
            height: `${r.height * 100}%`,
          }}
        />
      ))}
      {pageRegions.length > 0 && (
        <span className="viewer-highlight-chip">cited passage</span>
      )}
    </span>
  );
}

function PageText({ page, terms }: { page: PageOut; terms?: string[] }) {
  if (!page.text_html) {
    return <p className="viewer-fallback-hint">No extracted text for this page yet.</p>;
  }
  const html = terms?.length
    ? highlightTerms(page.text_html, terms)
    : page.text_html;
  return (
    <div
      className="viewer-text-content"
      // sanitized server-side: escaped text with only b/i/p/br + margin style
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export function DocumentViewer() {
  const { documentId } = useParams({ from: "/documents/$documentId" });
  const { page, highlight, citation } = useSearch({
    from: "/documents/$documentId",
  });
  const navigate = useNavigate();
  const [mode, setModeState] = useState<ViewMode>(loadMode);
  const [showNotes, setShowNotes] = useState(false);
  const [showText, setShowText] = useState(false);
  const [showMarks, setShowMarks] = useState(false);
  const [visiblePage, setVisiblePage] = useState(page);
  const touchStartX = useRef<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  function setMode(m: ViewMode) {
    localStorage.setItem("manabi-viewer-mode", m);
    setModeState(m);
  }

  const doc = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => api.get<DocumentDetail>(`/api/documents/${documentId}`),
  });

  const module = useQuery({
    queryKey: ["module", String(doc.data?.module_id)],
    queryFn: () => api.get<ModuleDetail>(`/api/modules/${doc.data!.module_id}`),
    enabled: doc.data != null,
  });

  // Module summary terms — for the "highlight key terms" audit view
  const summary = useQuery({
    queryKey: ["summary", String(doc.data?.module_id)],
    queryFn: () =>
      api.get<SummaryOut | null>(`/api/modules/${doc.data!.module_id}/summary`),
    enabled: doc.data != null && showText,
    staleTime: 60_000,
  });
  const termList = (summary.data?.key_terms ?? [])
    .map((t) => t.term)
    .concat((summary.data?.acronyms ?? []).map((a) => a.acronym));
  const activeTerms = showMarks ? termList : undefined;

  // Precise per-citation regions, falling back to chunk-level for old links
  const regions = useQuery({
    queryKey: ["regions", citation ?? null, highlight ?? null],
    queryFn: () =>
      citation != null
        ? api.get<RegionOut[]>(`/api/citations/${citation}/regions`)
        : api.get<RegionOut[]>(`/api/chunks/${highlight}/regions`),
    enabled: citation != null || highlight != null,
    staleTime: Infinity,
  });
  const regionList = regions.data ?? [];

  const total = doc.data?.pages.length ?? 0;
  const current = doc.data?.pages.find((p) => p.page_no === page);
  const isSlides = doc.data?.kind === "pptx";

  function goTo(n: number) {
    if (n < 1 || n > total) return;
    navigate({
      to: "/documents/$documentId",
      params: { documentId },
      // preserve highlight params so citations stay visible across pages
      search: {
        page: n,
        ...(highlight != null ? { highlight } : {}),
        ...(citation != null ? { citation } : {}),
      },
      replace: true,
    });
  }

  useEffect(() => {
    if (mode !== "single") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") goTo(page + 1);
      if (e.key === "ArrowLeft") goTo(page - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, total, mode]);

  // Scroll mode: keep the page counter in sync with what's on screen
  useEffect(() => {
    if (mode !== "scroll" || !scrollRef.current) return;
    const rows = scrollRef.current.querySelectorAll("[data-page-no]");
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setVisiblePage(Number((entry.target as HTMLElement).dataset.pageNo));
          }
        }
      },
      { root: scrollRef.current, threshold: 0.4 },
    );
    rows.forEach((r) => observer.observe(r));
    return () => observer.disconnect();
  }, [mode, doc.data]);

  // Entering scroll mode: jump to the current page
  useEffect(() => {
    if (mode !== "scroll") return;
    const el = scrollRef.current?.querySelector(`[data-page-no="${page}"]`);
    el?.scrollIntoView({ block: "start" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  if (doc.isLoading) return <div className="viewer-splash">Loading…</div>;
  if (doc.isError || !doc.data)
    return <div className="viewer-splash">Could not load document.</div>;

  const d = doc.data;

  return (
    <div className="viewer">
      <header className="viewer-head">
        <Link
          to="/courses/$courseId/modules/$moduleId"
          params={{
            courseId: String(module.data?.course_id ?? d.module_id),
            moduleId: String(d.module_id),
          }}
          search={{ tab: "materials" }}
          className="viewer-back"
        >
          <ChevronLeft size={16} strokeWidth={1.5} /> Back
        </Link>
        <span className="viewer-title" title={d.filename}>
          {d.filename}
        </span>
        <div className="viewer-tools">
          {isSlides && current?.speaker_notes && mode === "single" && (
            <button
              className={`icon-btn${showNotes ? " active" : ""}`}
              onClick={() => setShowNotes((v) => !v)}
              aria-label="Speaker notes"
            >
              <MessageSquareText size={17} strokeWidth={1.5} />
            </button>
          )}
          <button
            className={`icon-btn${showText ? " active" : ""}`}
            onClick={() => setShowText((v) => !v)}
            aria-label="Extracted text"
            title="Extracted text — selectable and searchable, even for scanned PDFs"
          >
            <Type size={17} strokeWidth={1.5} />
          </button>
          {showText && termList.length > 0 && (
            <button
              className={`icon-btn${showMarks ? " active" : ""}`}
              onClick={() => setShowMarks((v) => !v)}
              aria-label="Highlight key terms"
              title="Highlight the summary's key terms in the text — audit what the AI caught"
            >
              <Highlighter size={17} strokeWidth={1.5} />
            </button>
          )}
          <button
            className={`icon-btn${mode === "single" ? " active" : ""}`}
            onClick={() => setMode("single")}
            aria-label="Single page"
            title="One page at a time"
          >
            <Square size={17} strokeWidth={1.5} />
          </button>
          <button
            className={`icon-btn${mode === "scroll" ? " active" : ""}`}
            onClick={() => setMode("scroll")}
            aria-label="Continuous scroll"
            title="Scroll through all pages"
          >
            <GalleryVertical size={17} strokeWidth={1.5} />
          </button>
          <button
            className={`icon-btn${mode === "grid" ? " active" : ""}`}
            onClick={() => setMode("grid")}
            aria-label="All pages grid"
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

      {showMarks && showText && termList.length > 0 && (
        <p className="term-legend">
          {countTermsPresent(
            d.pages.map((p) => (p.text_html ?? "").replace(/<[^>]*>/g, " ")).join(" "),
            termList,
          )}{" "}
          of {termList.length} summary terms appear in this document's text
        </p>
      )}

      {mode === "grid" && (
        <div className="viewer-grid">
          {d.pages.map((p) => (
            <button
              key={p.page_no}
              className={`grid-cell${p.page_no === page ? " current" : ""}`}
              onClick={() => {
                goTo(p.page_no);
                setMode("single");
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
      )}

      {mode === "scroll" && (
        <div className="viewer-scroll" ref={scrollRef}>
          {d.pages.map((p) => (
            <div
              key={p.page_no}
              className={`scroll-row${showText ? " with-text" : ""}`}
              data-page-no={p.page_no}
            >
              <div className="scroll-render">
                {p.has_render ? (
                  <PageImage
                    documentId={documentId}
                    page={p}
                    regions={regionList}
                    lazy
                  />
                ) : (
                  <div className="viewer-text-fallback">
                    <h2>{p.title ?? `Page ${p.page_no}`}</h2>
                  </div>
                )}
                <span className="scroll-page-no mono">{p.page_no}</span>
              </div>
              {showText && (
                <div className="scroll-text">
                  <PageText page={p} terms={activeTerms} />
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {mode === "single" && (
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
          {showText && current ? (
            <div className="viewer-text-panel">
              <h3 className="viewer-text-head">
                Extracted text — {isSlides ? "slide" : "page"} {page}
              </h3>
              <PageText page={current} terms={activeTerms} />
            </div>
          ) : current?.has_render ? (
            <PageImage documentId={documentId} page={current} regions={regionList} />
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

      {showNotes && current?.speaker_notes && mode === "single" && (
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

      {mode === "single" && (
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

      {mode === "scroll" && (
        <footer className="viewer-nav">
          <span className="page-total mono">
            {visiblePage} / {total}
          </span>
        </footer>
      )}
    </div>
  );
}
