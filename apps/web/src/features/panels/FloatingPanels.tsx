import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { FloatingPanel } from "./FloatingPanel";
import "./floating-panels.css";

export type PanelKind = "materials" | "summary" | "chat" | "notes" | "document";

export interface Panel {
  id: string; // `${kind}:${moduleId}` (or `document:${documentId}`) — one each
  kind: PanelKind;
  moduleId: string;
  courseId: string;
  documentId?: string; // set only for kind === "document"
  title: string; // course/module label shown in the panel header
  x: number;
  y: number;
  w: number;
  h: number;
  z: number;
}

export type PanelOpen = Pick<
  Panel,
  "kind" | "moduleId" | "courseId" | "title"
> & { documentId?: string };

interface Ctx {
  panels: Panel[];
  open: (p: PanelOpen) => void;
  close: (id: string) => void;
  focus: (id: string) => void;
  move: (id: string, patch: Partial<Pick<Panel, "x" | "y" | "w" | "h">>) => void;
}

const FloatingPanelContext = createContext<Ctx | null>(null);

export function useFloatingPanels(): Ctx {
  const ctx = useContext(FloatingPanelContext);
  if (!ctx) throw new Error("useFloatingPanels must be used within provider");
  return ctx;
}

const STORAGE_KEY = "manabi-panels-v1";
const BASE_Z = 63; // free band is 62–79 (chat-panel 61, drawers 70/71, search 80)

function loadPanels(): Panel[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const arr = raw ? (JSON.parse(raw) as Panel[]) : [];
    return Array.isArray(arr) ? arr.slice(0, 6) : [];
  } catch {
    return [];
  }
}

export function FloatingPanelProvider({ children }: { children: ReactNode }) {
  const [panels, setPanels] = useState<Panel[]>(loadPanels);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(panels));
    } catch {
      /* quota / private mode — panels just won't persist */
    }
  }, [panels]);

  const open = useCallback((p: PanelOpen) => {
    const id =
      p.kind === "document" ? `document:${p.documentId}` : `${p.kind}:${p.moduleId}`;
    setPanels((prev) => {
      const existing = prev.find((x) => x.id === id);
      const z = prev.reduce((m, x) => Math.max(m, x.z), BASE_Z) + 1;
      if (existing) {
        return prev.map((x) => (x.id === id ? { ...x, z } : x)); // focus
      }
      // Cascade new panels so they don't stack exactly.
      const n = prev.length;
      const w = Math.min(520, window.innerWidth - 40);
      const h = Math.min(620, window.innerHeight - 80);
      return [
        ...prev,
        {
          ...p,
          id,
          w,
          h,
          x: Math.max(12, Math.min(120 + n * 28, window.innerWidth - w - 12)),
          y: Math.max(12, Math.min(72 + n * 28, window.innerHeight - h - 12)),
          z,
        },
      ];
    });
  }, []);

  const close = useCallback(
    (id: string) => setPanels((prev) => prev.filter((p) => p.id !== id)),
    [],
  );
  const focus = useCallback(
    (id: string) =>
      setPanels((prev) => {
        const z = prev.reduce((m, x) => Math.max(m, x.z), BASE_Z) + 1;
        return prev.map((p) => (p.id === id ? { ...p, z } : p));
      }),
    [],
  );
  const move = useCallback(
    (id: string, patch: Partial<Pick<Panel, "x" | "y" | "w" | "h">>) =>
      setPanels((prev) => prev.map((p) => (p.id === id ? { ...p, ...patch } : p))),
    [],
  );

  return (
    <FloatingPanelContext.Provider value={{ panels, open, close, focus, move }}>
      {children}
      <FloatingPanelStack panels={panels} />
    </FloatingPanelContext.Provider>
  );
}

function FloatingPanelStack({ panels }: { panels: Panel[] }) {
  const { close, focus, move } = useFloatingPanels();
  if (panels.length === 0) return null;
  // On a phone only the front-most panel is shown, as a bottom sheet.
  const mobile = window.matchMedia("(max-width: 767px)").matches;
  const shown = mobile
    ? [panels.reduce((top, p) => (p.z > top.z ? p : top), panels[0])]
    : panels;
  return createPortal(
    <>
      {shown.map((p) => (
        <FloatingPanel
          key={p.id}
          panel={p}
          mobile={mobile}
          onClose={() => close(p.id)}
          onFocus={() => focus(p.id)}
          onMove={(patch) => move(p.id, patch)}
        />
      ))}
    </>,
    document.body,
  );
}
