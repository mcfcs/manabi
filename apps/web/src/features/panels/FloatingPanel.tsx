import { GripHorizontal, X } from "lucide-react";
import { type PointerEvent as ReactPointerEvent, useEffect, useRef } from "react";

import { SummaryTab } from "../ai/SummaryTab";
import { ChatTab } from "../chat/ChatTab";
import { MaterialsTab } from "../materials/MaterialsTab";
import { NotesTab } from "../notes/NotesTab";
import { DocumentViewer } from "../viewer/DocumentViewer";
import { useFloatingPanels, type Panel } from "./FloatingPanels";

const KIND_LABEL: Record<Panel["kind"], string> = {
  materials: "Materials",
  summary: "Summary",
  chat: "Chat",
  notes: "Notes",
  document: "Material",
};

function PanelContent({ panel }: { panel: Panel }) {
  const { open } = useFloatingPanels();
  switch (panel.kind) {
    case "materials":
      return (
        <MaterialsTab
          moduleId={panel.moduleId}
          onOpenDocument={(doc) =>
            open({
              kind: "document",
              moduleId: panel.moduleId,
              courseId: panel.courseId,
              documentId: String(doc.id),
              title: doc.filename,
            })
          }
        />
      );
    case "summary":
      return <SummaryTab moduleId={panel.moduleId} />;
    case "chat":
      return <ChatTab moduleId={panel.moduleId} />;
    case "notes":
      return <NotesTab moduleId={panel.moduleId} />;
    case "document":
      return <DocumentViewer documentId={panel.documentId} />;
  }
}

export function FloatingPanel({
  panel,
  mobile,
  onClose,
  onFocus,
  onMove,
}: {
  panel: Panel;
  mobile: boolean;
  onClose: () => void;
  onFocus: () => void;
  onMove: (patch: Partial<Pick<Panel, "x" | "y" | "w" | "h">>) => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  // Persist native CSS resize back to panel state (so size survives reloads).
  useEffect(() => {
    if (mobile) return;
    const el = panelRef.current;
    if (!el) return;
    let raf = 0;
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() =>
        onMove({ w: el.offsetWidth, h: el.offsetHeight }),
      );
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [mobile, onMove]);

  // Drag by the header (desktop only). Pointer events on window so the drag
  // keeps up even if the cursor outruns the header.
  function onDragStart(e: ReactPointerEvent) {
    if (mobile || e.button !== 0) return;
    onFocus();
    const sx = e.clientX;
    const sy = e.clientY;
    const ox = panel.x;
    const oy = panel.y;
    const onPointerMove = (ev: PointerEvent) => {
      onMove({
        x: Math.max(0, Math.min(ox + ev.clientX - sx, window.innerWidth - 80)),
        y: Math.max(0, Math.min(oy + ev.clientY - sy, window.innerHeight - 40)),
      });
    };
    const onPointerUp = () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
    };
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  }

  const header = (
    <header
      className="fp-head"
      onPointerDown={mobile ? undefined : onDragStart}
    >
      {!mobile && <GripHorizontal size={15} strokeWidth={1.75} className="fp-grip" />}
      <span className="fp-title">
        {panel.title} · {KIND_LABEL[panel.kind]}
      </span>
      <button className="icon-btn" onClick={onClose} aria-label="Close panel">
        <X size={16} strokeWidth={1.75} />
      </button>
    </header>
  );

  if (mobile) {
    return (
      <>
        <div className="fp-backdrop" onClick={onClose} />
        <div className="fp fp-sheet" style={{ zIndex: panel.z }}>
          {header}
          <div className="fp-body">
            <PanelContent panel={panel} />
          </div>
        </div>
      </>
    );
  }

  return (
    <div
      ref={panelRef}
      className="fp"
      style={{ left: panel.x, top: panel.y, width: panel.w, height: panel.h, zIndex: panel.z }}
      onPointerDownCapture={onFocus}
    >
      {header}
      <div className="fp-body">
        <PanelContent panel={panel} />
      </div>
    </div>
  );
}
