import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Modal } from "../../components/Modal";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import {
  AArrowDown,
  AArrowUp,
  AlignJustify,
  AlignLeft,
  FileSearch,
  ChevronLeft,
  ChevronRight,
  Download,
  GalleryVertical,
  Highlighter,
  LayoutGrid,
  MessageSquareText,
  NotebookPen,
  Pencil,
  Sparkles,
  Square,
  Type,
  X,
} from "lucide-react";
import { type RefObject, useEffect, useRef, useState } from "react";

import {
  api,
  type AnnotationOut,
  type ChatThreadOut,
  type DocumentDetail,
  type ModuleDetail,
  type PageOut,
  type ReaderOut,
  type RegionOut,
  type SummaryOut,
} from "../../lib/api";
import { ChatPanel } from "../chat/ChatPanel";
import {
  type AnnotationMark,
  countTermsPresent,
  useHighlightedHtml,
} from "../../lib/highlight";
import {
  AnnotationEditor,
  AnnotationPicker,
  AnnotationsPanel,
  type PendingSelection,
  SelectionPopover,
  useAnnotations,
} from "./annotations";
import "./viewer.css";

type ViewMode = "single" | "scroll" | "grid" | "original" | "read";

function loadMode(): ViewMode {
  const saved = localStorage.getItem("manabi-viewer-mode");
  return saved === "single" ||
    saved === "grid" ||
    saved === "original" ||
    saved === "read"
    ? saved
    : "scroll";
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
        // The SW revalidates this (NetworkFirst) so a re-extract/re-split render
        // is never stale; the endpoint's ETag makes unchanged pages a cheap 304.
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

function PageText({
  page,
  terms,
  annotations,
  onAnnotClick,
}: {
  page: PageOut;
  terms?: string[];
  annotations?: AnnotationOut[];
  onAnnotClick?: (ids: number[], at: { x: number; y: number }) => void;
}) {
  const html = page.text_html ?? "";
  const annotMarks: AnnotationMark[] = (annotations ?? []).map((a) => ({
    id: a.id,
    quote: a.quote,
    color: a.color,
    hasNote: !!a.note,
  }));
  // Whole-word terms + cross-tag annotations, baked into the rendered HTML.
  const marked = useHighlightedHtml(html, terms, annotMarks);
  if (!page.text_html) {
    return <p className="viewer-fallback-hint">No extracted text for this page yet.</p>;
  }
  return (
    <div
      className="viewer-text-content"
      // sanitized server-side: escaped text; b/i/p/br/code/table + margin style
      dangerouslySetInnerHTML={{ __html: marked }}
      onClick={(e) => {
        const mark = (e.target as HTMLElement).closest("mark.annot");
        const raw = mark?.getAttribute("data-annot-ids");
        if (raw && onAnnotClick)
          onAnnotClick(raw.split(",").map(Number), { x: e.clientX, y: e.clientY });
      }}
    />
  );
}

/** Container-level text-selection → popover, working for both mouse and touch
 * (iOS never fires onMouseUp for a long-press selection). Tracks a valid,
 * in-container selection via `selectionchange` (debounced) and presents the
 * popover on pointerup/touchend, after the touch settles. */
function useSelectionPopover({
  containerRef,
  mode,
  visiblePage,
  onSelect,
}: {
  containerRef: RefObject<HTMLElement | null>;
  mode: ViewMode;
  visiblePage: number;
  onSelect: (sel: PendingSelection) => void;
}) {
  const pending = useRef<PendingSelection | null>(null);
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    let debounce: number | undefined;

    const capture = () => {
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0 || sel.isCollapsed) {
        pending.current = null;
        return;
      }
      const range = sel.getRangeAt(0);
      if (!container.contains(range.commonAncestorContainer)) {
        pending.current = null;
        return;
      }
      const text = sel.toString().replace(/\s+/g, " ").trim();
      if (text.length < 3) {
        pending.current = null;
        return;
      }
      let pageNo = visiblePage;
      if (mode !== "read") {
        const start = range.startContainer;
        const el =
          start.nodeType === Node.ELEMENT_NODE
            ? (start as Element)
            : start.parentElement;
        const holder = el?.closest("[data-page-no]");
        const pn = holder?.getAttribute("data-page-no");
        if (pn) pageNo = Number(pn);
      }
      const rect = range.getBoundingClientRect();
      const POP_W = 236;
      pending.current = {
        quote: text.slice(0, 2000),
        pageNo,
        x: Math.max(8, Math.min(rect.left, window.innerWidth - POP_W - 8)),
        y:
          rect.bottom + 8 + 52 > window.innerHeight
            ? Math.max(8, rect.top - 52)
            : rect.bottom + 8,
      };
    };

    const onSelectionChange = () => {
      window.clearTimeout(debounce);
      debounce = window.setTimeout(capture, 150);
    };
    const finalize = () => {
      window.clearTimeout(debounce);
      // Defer so the browser finalizes the selection after the touch/click ends
      // (on iOS the same touch would otherwise dismiss the just-shown popover).
      window.setTimeout(() => {
        capture();
        if (pending.current) onSelect(pending.current);
      }, 0);
    };

    document.addEventListener("selectionchange", onSelectionChange);
    container.addEventListener("pointerup", finalize);
    container.addEventListener("touchend", finalize);
    return () => {
      window.clearTimeout(debounce);
      document.removeEventListener("selectionchange", onSelectionChange);
      container.removeEventListener("pointerup", finalize);
      container.removeEventListener("touchend", finalize);
    };
  }, [containerRef, mode, visiblePage, onSelect]);
}

/** The continuous merged-document text (Reader + scroll text column). Highlights
 * are baked into the HTML string via useHighlightedHtml (pure), so React owns
 * the marks — no post-render DOM mutation that could race with a re-render. */
function ContinuousText({
  html,
  terms,
  annots,
  onAnnotClick,
}: {
  html: string;
  terms?: string[];
  annots: AnnotationMark[];
  onAnnotClick: (ids: number[], at: { x: number; y: number }) => void;
}) {
  const marked = useHighlightedHtml(html, terms, annots);
  return (
    <article
      className="reader-doc note-editor-content"
      onClick={(e) => {
        const mark = (e.target as HTMLElement).closest("mark.annot");
        const raw = mark?.getAttribute("data-annot-ids");
        if (raw)
          onAnnotClick(raw.split(",").map(Number), { x: e.clientX, y: e.clientY });
      }}
      // selection via useSelectionPopover; marks are part of the rendered HTML
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: marked }}
    />
  );
}

/** Shown in place of a page image when no render exists — the page's extracted
 * text (stripped) if we have it, else a small muted note. Replaces the old big
 * serif "Page N" placeholder that leaked through when a render was missing. */
function PageFallback({ page, isSlides }: { page: PageOut; isSlides: boolean }) {
  const text = (page.text_html ?? "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const noun = isSlides ? "slide" : "page";
  return (
    <div className="viewer-text-fallback">
      {text ? (
        <p className="viewer-fallback-text">
          {text.slice(0, 500)}
          {text.length > 500 ? "…" : ""}
        </p>
      ) : (
        <p className="viewer-fallback-hint">No image available for this {noun}.</p>
      )}
    </div>
  );
}

export function DocumentViewer() {
  const { documentId } = useParams({ from: "/documents/$documentId" });
  const { page, highlight, citation } = useSearch({
    from: "/documents/$documentId",
  });
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [mode, setModeState] = useState<ViewMode>(loadMode);
  const [showNotes, setShowNotes] = useState(false);
  const [showText, setShowText] = useState(false);
  const [showMarks, setShowMarks] = useState(false);
  // Split view text layout: per-page (default — right for slides/PPTX) vs one
  // continuous merged document. Off by default; persisted per device.
  const [showContinuous, setShowContinuous] = useState(
    () => localStorage.getItem("manabi-viewer-continuous") === "1",
  );
  function toggleContinuous() {
    setShowContinuous((v) => {
      localStorage.setItem("manabi-viewer-continuous", v ? "0" : "1");
      return !v;
    });
  }
  const [visiblePage, setVisiblePage] = useState(page);
  const [textSize, setTextSize] = useState(
    () => Number(localStorage.getItem("manabi-viewer-textsize")) || 16,
  );
  function bumpTextSize(delta: number) {
    setTextSize((s) => {
      const next = Math.min(24, Math.max(13, s + delta));
      localStorage.setItem("manabi-viewer-textsize", String(next));
      return next;
    });
  }
  // Continuous merged text — used by the Reader (read mode) and the scroll
  // view's text column, so a paragraph never cuts at a page edge.
  const reader = useQuery({
    queryKey: ["reader", documentId],
    queryFn: () => api.get<ReaderOut>(`/api/documents/${documentId}/reader`),
    enabled:
      mode === "read" || (mode === "scroll" && showText && showContinuous),
    staleTime: 60_000,
  });
  const touchStartX = useRef<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<HTMLDivElement>(null);

  // Annotations
  const annots = useAnnotations(documentId);
  const [selection, setSelection] = useState<PendingSelection | null>(null);
  const [editingAnnot, setEditingAnnot] = useState<number | null>(null);
  // When a click lands on overlapping highlights, ask which one to open.
  const [annotPick, setAnnotPick] = useState<{
    ids: number[];
    x: number;
    y: number;
  } | null>(null);
  const [showAnnotPanel, setShowAnnotPanel] = useState(false);
  const [editingPageText, setEditingPageText] = useState<number | null>(null);

  function handleAnnotClick(ids: number[], at: { x: number; y: number }) {
    if (ids.length <= 1) setEditingAnnot(ids[0] ?? null);
    else setAnnotPick({ ids, x: at.x, y: at.y });
  }

  // Ask-Steven discussions anchored to this document
  const [discuss, setDiscuss] = useState<ChatThreadOut | null>(null);
  const [showDiscussions, setShowDiscussions] = useState(false);
  const docThreads = useQuery({
    queryKey: ["document-threads", documentId],
    queryFn: () => api.get<ChatThreadOut[]>(`/api/documents/${documentId}/threads`),
  });

  async function startDiscussion(quote: string, pageNo: number | null) {
    const thread = await api.post<ChatThreadOut>(
      `/api/documents/${documentId}/discuss`,
      { quote: quote.slice(0, 2000), page: pageNo },
    );
    queryClient.invalidateQueries({ queryKey: ["document-threads", documentId] });
    setDiscuss(thread); // panel prompts for a question (or explains on send)
  }
  const annotsByPage = new Map<number, AnnotationOut[]>();
  for (const a of annots.list.data ?? []) {
    annotsByPage.set(a.page_no, [...(annotsByPage.get(a.page_no) ?? []), a]);
  }
  // Flattened marks for the continuous Reader (no per-page split there).
  const allAnnotMarks: AnnotationMark[] = (annots.list.data ?? []).map((a) => ({
    id: a.id,
    quote: a.quote,
    color: a.color,
    hasNote: !!a.note,
  }));
  const editingAnnotation =
    (annots.list.data ?? []).find((a) => a.id === editingAnnot) ?? null;

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

  // Module summary terms — for the "highlight key terms" audit view. Fetched
  // for both the per-page text panels and the continuous Reader.
  const termsEnabled = showText || mode === "read";
  const summary = useQuery({
    queryKey: ["summary", String(doc.data?.module_id)],
    queryFn: () =>
      api.get<SummaryOut | null>(`/api/modules/${doc.data!.module_id}/summary`),
    enabled: doc.data != null && termsEnabled,
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
    // re-observe when the row layout changes (per-page ⇄ continuous, text on/off)
  }, [mode, doc.data, showText, showContinuous]);

  // Entering scroll mode: jump to the current page
  useEffect(() => {
    if (mode !== "scroll") return;
    const el = scrollRef.current?.querySelector(`[data-page-no="${page}"]`);
    el?.scrollIntoView({ block: "start" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  // One selection→popover handler covering every mode (only one renders at a
  // time); mouse and touch both, so highlighting works on iOS.
  useSelectionPopover({
    containerRef: viewerRef,
    mode,
    visiblePage: mode === "scroll" ? visiblePage : page,
    onSelect: setSelection,
  });

  if (doc.isLoading) return <div className="viewer-splash">Loading…</div>;
  if (doc.isError || !doc.data)
    return <div className="viewer-splash">Could not load document.</div>;

  const d = doc.data;

  return (
    <div
      className="viewer"
      ref={viewerRef}
      style={{ ["--reader-size" as string]: `${textSize}px` }}
    >
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
          {mode === "scroll" && showText && (
            <button
              className={`icon-btn${showContinuous ? " active" : ""}`}
              onClick={toggleContinuous}
              aria-label="Whole document as one"
              title={
                showContinuous
                  ? "Text: one continuous document — click for per-page text"
                  : "Text: per page (best for slides) — click to merge into one continuous document"
              }
            >
              <AlignJustify size={17} strokeWidth={1.5} />
            </button>
          )}
          {termsEnabled && (
            <button
              className={`icon-btn${showAnnotPanel ? " active" : ""}`}
              onClick={() => setShowAnnotPanel((v) => !v)}
              aria-label="Annotations"
              title="Your highlights and notes on this document"
            >
              <NotebookPen size={17} strokeWidth={1.5} />
            </button>
          )}
          {termsEnabled && termList.length > 0 && (
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
            className={`icon-btn${showDiscussions ? " active" : ""}`}
            onClick={() => setShowDiscussions((v) => !v)}
            aria-label="Ask Steven / discussions"
            title="Ask Steven about this file, and revisit saved discussions"
          >
            <Sparkles size={17} strokeWidth={1.5} />
            {(docThreads.data?.length ?? 0) > 0 && (
              <span className="viewer-discuss-count">{docThreads.data!.length}</span>
            )}
          </button>
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
          <button
            className={`icon-btn${mode === "read" ? " active" : ""}`}
            onClick={() => setMode("read")}
            aria-label="Read as one document"
            title="Whole document as one continuous, flowing text"
          >
            <AlignLeft size={17} strokeWidth={1.5} />
          </button>
          {d.kind === "pdf" && (
            <button
              className={`icon-btn${mode === "original" ? " active" : ""}`}
              onClick={() => setMode("original")}
              aria-label="Original PDF"
              title="Browser PDF viewer — Ctrl+F and copy/paste work natively"
            >
              <FileSearch size={17} strokeWidth={1.5} />
            </button>
          )}
          {(mode === "read" || showText) && (
            <span className="viewer-textsize" role="group" aria-label="Text size">
              <button
                className="icon-btn"
                onClick={() => bumpTextSize(-1)}
                aria-label="Smaller text"
                title="Smaller text"
              >
                <AArrowDown size={17} strokeWidth={1.5} />
              </button>
              <button
                className="icon-btn"
                onClick={() => bumpTextSize(1)}
                aria-label="Larger text"
                title="Larger text"
              >
                <AArrowUp size={17} strokeWidth={1.5} />
              </button>
            </span>
          )}
          <a
            className="icon-btn"
            href={`/api/documents/${documentId}/original`}
            aria-label="Download original"
          >
            <Download size={17} strokeWidth={1.5} />
          </a>
        </div>
      </header>

      {showMarks && termsEnabled && termList.length > 0 && (
        <p className="term-legend">
          {countTermsPresent(
            d.pages.map((p) => (p.text_html ?? "").replace(/<[^>]*>/g, " ")).join(" "),
            termList,
          )}{" "}
          of {termList.length} summary terms appear in this document's text
        </p>
      )}

      {mode === "read" && (
        <div className="viewer-read">
          {reader.isLoading && <div className="viewer-splash">Loading…</div>}
          {reader.data && (
            <ContinuousText
              html={reader.data.html}
              terms={activeTerms}
              annots={allAnnotMarks}
              onAnnotClick={handleAnnotClick}
            />
          )}
        </div>
      )}

      {mode === "original" && (
        <iframe
          className="viewer-original"
          // When actually split, the logical page number no longer maps to the
          // original PDF's page — open the original without a jump.
          src={
            d.page_layout === "spread"
              ? `/api/documents/${documentId}/original?inline=1`
              : `/api/documents/${documentId}/original?inline=1#page=${page}`
          }
          title={d.filename}
        />
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

      {mode === "scroll" &&
        (showText && showContinuous ? (
          // Whole document as one: page images stacked beside one continuous
          // merged-text column (paragraphs don't cut at page edges).
          <div className="viewer-scroll two-col" ref={scrollRef}>
            <div className="scroll-images">
              {d.pages.map((p) => (
                <div key={p.page_no} className="scroll-row" data-page-no={p.page_no}>
                  <div className="scroll-render">
                    {p.has_render ? (
                      <PageImage
                        documentId={documentId}
                        page={p}
                        regions={regionList}
                        lazy
                      />
                    ) : (
                      <PageFallback page={p} isSlides={isSlides} />
                    )}
                    <span className="scroll-page-no mono">{p.page_no}</span>
                  </div>
                </div>
              ))}
            </div>
            <div className="scroll-continuous">
              {reader.isLoading && (
                <div className="viewer-splash">Loading text…</div>
              )}
              {reader.data && (
                <ContinuousText
                  html={reader.data.html}
                  terms={activeTerms}
                  annots={allAnnotMarks}
                  onAnnotClick={handleAnnotClick}
                />
              )}
            </div>
          </div>
        ) : (
          // Per-page (default): each page image with its own extracted text
          // beside it — right for slides/PPTX where text is per-slide.
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
                    <PageFallback page={p} isSlides={isSlides} />
                  )}
                  <span className="scroll-page-no mono">{p.page_no}</span>
                </div>
                {showText && (
                  <div className="scroll-text">
                    <div className="text-panel-tools">
                      <button
                        className="icon-btn"
                        onClick={() => setEditingPageText(p.page_no)}
                        aria-label="Edit extracted text"
                        title="Edit this page's extracted text"
                      >
                        <Pencil size={13} strokeWidth={1.5} />
                      </button>
                    </div>
                    <PageText
                      page={p}
                      terms={activeTerms}
                      annotations={annotsByPage.get(p.page_no)}
                      onAnnotClick={handleAnnotClick}
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
        ))}

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
            <div className="viewer-text-panel" data-page-no={page}>
              <h3 className="viewer-text-head">
                Extracted text — {isSlides ? "slide" : "page"} {page}
                <button
                  className="icon-btn"
                  onClick={() => setEditingPageText(page)}
                  aria-label="Edit extracted text"
                  title="Edit this page's extracted text"
                >
                  <Pencil size={13} strokeWidth={1.5} />
                </button>
              </h3>
              <PageText
                page={current}
                terms={activeTerms}
                annotations={annotsByPage.get(page)}
                onAnnotClick={handleAnnotClick}
              />
            </div>
          ) : current?.has_render ? (
            <PageImage
              documentId={documentId}
              page={current}
              regions={regionList}
            />
          ) : current ? (
            <PageFallback page={current} isSlides={isSlides} />
          ) : null}
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

      {selection && (
        <SelectionPopover
          selection={selection}
          onHighlight={(color, note) => {
            annots.create.mutate({
              page_no: selection.pageNo,
              quote: selection.quote,
              note,
              color,
            });
            setSelection(null);
            window.getSelection()?.removeAllRanges();
          }}
          onDismiss={() => setSelection(null)}
          onAsk={() => {
            const quote = selection.quote;
            const pageNo = selection.pageNo;
            setSelection(null);
            window.getSelection()?.removeAllRanges();
            startDiscussion(quote, pageNo);
          }}
        />
      )}

      {editingAnnotation && (
        <AnnotationEditor
          annotation={editingAnnotation}
          onSave={(note) => {
            annots.update.mutate({ id: editingAnnotation.id, note });
            setEditingAnnot(null);
          }}
          onDelete={() => {
            annots.remove.mutate(editingAnnotation.id);
            setEditingAnnot(null);
          }}
          onClose={() => setEditingAnnot(null)}
        />
      )}

      {annotPick && (
        <AnnotationPicker
          annotations={(annots.list.data ?? []).filter((a) =>
            annotPick.ids.includes(a.id),
          )}
          x={annotPick.x}
          y={annotPick.y}
          onPick={(id) => {
            setAnnotPick(null);
            setEditingAnnot(id);
          }}
          onClose={() => setAnnotPick(null)}
        />
      )}

      {showAnnotPanel && (
        <AnnotationsPanel
          annotations={annots.list.data ?? []}
          onJump={(a) => {
            goTo(a.page_no);
            if (mode === "scroll") {
              scrollRef.current
                ?.querySelector(`[data-page-no="${a.page_no}"]`)
                ?.scrollIntoView({ block: "start" });
            }
          }}
          onClose={() => setShowAnnotPanel(false)}
        />
      )}

      {editingPageText != null && (
        <PageTextEditModal
          documentId={documentId}
          page={d.pages.find((p) => p.page_no === editingPageText)!}
          onClose={() => setEditingPageText(null)}
        />
      )}

      {showDiscussions && (
        <div className="viewer-discuss">
          <div className="viewer-discuss-head">
            <span>Ask Steven</span>
            <button
              className="icon-btn"
              onClick={() => setShowDiscussions(false)}
              aria-label="Close"
            >
              <X size={15} strokeWidth={1.75} />
            </button>
          </div>
          <button
            className="btn viewer-discuss-page"
            onClick={() => {
              const pageNo = mode === "scroll" ? visiblePage : page;
              const pg = d.pages.find((p) => p.page_no === pageNo);
              const text = (pg?.text_html ?? "")
                .replace(/<[^>]+>/g, " ")
                .replace(/\s+/g, " ")
                .trim();
              if (text) {
                setShowDiscussions(false);
                startDiscussion(text.slice(0, 1500), pageNo);
              }
            }}
          >
            <Sparkles size={14} strokeWidth={1.75} /> Ask about this{" "}
            {isSlides ? "slide" : "page"}
          </button>
          <p className="viewer-discuss-hint">
            Or highlight any text in the page to ask about a passage.
          </p>
          <div className="viewer-discuss-list">
            {(docThreads.data ?? []).length === 0 && (
              <p className="viewer-discuss-empty">No discussions yet.</p>
            )}
            {(docThreads.data ?? []).map((t) => (
              <button
                key={t.id}
                className="viewer-discuss-item"
                onClick={() => {
                  setShowDiscussions(false);
                  setDiscuss(t);
                }}
              >
                {t.source_page != null && (
                  <span className="viewer-discuss-pg mono">p.{t.source_page}</span>
                )}
                <span className="viewer-discuss-quote">
                  {t.source_quote ?? t.title}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {discuss && (
        <ChatPanel
          moduleId={String(d.module_id)}
          thread={discuss}
          onClose={() => setDiscuss(null)}
        />
      )}
    </div>
  );
}

function PageTextEditModal({
  documentId,
  page,
  onClose,
}: {
  documentId: string;
  page: PageOut;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [text, setText] = useState(() =>
    (page.text_html ?? "")
      .replace(/<\/p>/g, "\n\n")
      .replace(/<br\s*\/?>/g, "\n")
      .replace(/<[^>]*>/g, "")
      .replace(/&amp;/g, "&")
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&quot;/g, '"')
      .replace(/&#x27;/g, "'")
      .trim(),
  );
  const save = useMutation({
    mutationFn: () =>
      api.patch(`/api/documents/${documentId}/pages/${page.page_no}/text`, { text }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["document", documentId] });
      onClose();
    },
  });
  return (
    <Modal title={`Edit extracted text — page ${page.page_no}`} onClose={onClose}>
      <div className="modal-form">
        <textarea
          className="input page-text-edit"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={16}
        />
        <p className="gen-hint">
          Blank lines separate paragraphs. Your edit replaces the extracted
          text for reading and won't be overwritten by re-extraction.
        </p>
        {save.isError && <p className="error-text">{(save.error as Error).message}</p>}
        <div className="modal-actions">
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            disabled={save.isPending}
            onClick={() => save.mutate()}
          >
            Save text
          </button>
        </div>
      </div>
    </Modal>
  );
}
