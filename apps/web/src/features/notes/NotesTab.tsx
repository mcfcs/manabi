import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Mathematics } from "@tiptap/extension-mathematics";
import { Table } from "@tiptap/extension-table";
import { TableCell } from "@tiptap/extension-table-cell";
import { TableHeader } from "@tiptap/extension-table-header";
import { TableRow } from "@tiptap/extension-table-row";
import { TaskItem } from "@tiptap/extension-task-item";
import { TaskList } from "@tiptap/extension-task-list";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import "katex/dist/katex.min.css";
import {
  AArrowDown,
  AArrowUp,
  Bold,
  CheckSquare,
  Code,
  FileDown,
  Heading1,
  Heading2,
  Italic,
  List,
  ListOrdered,
  Quote,
  Redo2,
  Strikethrough,
  Table as TableIcon,
  Undo2,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, type NoteOut } from "../../lib/api";
import "./notes.css";

type SaveState = "saved" | "saving" | "error" | "idle";

// Page tints for the note sheet — distinct from the app's --paper background
const TINTS = [
  { name: "White", value: "#FFFFFF" },
  { name: "Warm", value: "#FFFDF6" },
  { name: "Cream", value: "#FAF3E3" },
  { name: "Mist", value: "#F1F5FA" },
  { name: "Mint", value: "#EFF6EF" },
];

export function NotesTab({ moduleId }: { moduleId: string }) {
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [tint, setTint] = useState(
    () => localStorage.getItem("manabi-note-tint") ?? TINTS[0].value,
  );
  const [fontSize, setFontSize] = useState(
    () => Number(localStorage.getItem("manabi-note-fontsize")) || 16,
  );

  function pickTint(value: string) {
    setTint(value);
    localStorage.setItem("manabi-note-tint", value);
  }

  function bumpFontSize(delta: number) {
    setFontSize((size) => {
      const next = Math.min(22, Math.max(13, size + delta));
      localStorage.setItem("manabi-note-fontsize", String(next));
      return next;
    });
  }
  const debounceRef = useRef<number | null>(null);
  const pendingRef = useRef<Record<string, unknown> | null>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);

  const note = useQuery({
    queryKey: ["note", moduleId],
    queryFn: () => api.get<NoteOut>(`/api/modules/${moduleId}/note`),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  const queryClient = useQueryClient();
  const save = useCallback(
    async (pmJson: Record<string, unknown>) => {
      setSaveState("saving");
      try {
        // keepalive: the flush from pagehide must survive navigation
        const saved = await api.put<NoteOut>(
          `/api/modules/${moduleId}/note`,
          { pm_json: pmJson },
          { keepalive: true },
        );
        // Keep the cache mirroring the server — otherwise returning to this
        // tab re-initializes the editor from a stale pre-save snapshot
        // (and typing into that would overwrite the real note).
        queryClient.setQueryData(["note", moduleId], saved);
        pendingRef.current = null;
        setSaveState("saved");
      } catch {
        setSaveState("error");
      }
    },
    [moduleId, queryClient],
  );

  const editor = useEditor(
    {
      extensions: [
        StarterKit,
        Table.configure({ resizable: false }),
        TableRow,
        TableHeader,
        TableCell,
        TaskList,
        TaskItem.configure({ nested: true }),
        Mathematics,
      ],
      content: note.data?.pm_json ?? "",
      editorProps: {
        attributes: { class: "note-editor-content", spellcheck: "true" },
      },
      onUpdate: ({ editor }) => {
        pendingRef.current = editor.getJSON() as Record<string, unknown>;
        if (debounceRef.current) window.clearTimeout(debounceRef.current);
        debounceRef.current = window.setTimeout(() => {
          if (pendingRef.current) save(pendingRef.current);
        }, 800);
      },
    },
    [note.data != null],
  );

  // Flush unsaved changes when leaving / backgrounding
  useEffect(() => {
    const flush = () => {
      if (pendingRef.current) save(pendingRef.current);
    };
    window.addEventListener("visibilitychange", flush);
    window.addEventListener("pagehide", flush);
    return () => {
      flush();
      window.removeEventListener("visibilitychange", flush);
      window.removeEventListener("pagehide", flush);
    };
  }, [save]);

  // Keep the toolbar visible above the mobile keyboard (VisualViewport)
  useEffect(() => {
    const vv = window.visualViewport;
    const bar = toolbarRef.current;
    if (!vv || !bar) return;
    const reposition = () => {
      const keyboardOpen = vv.height < window.innerHeight - 120;
      if (keyboardOpen) {
        bar.style.position = "fixed";
        bar.style.top = `${vv.offsetTop + vv.height - bar.offsetHeight}px`;
        bar.style.left = "0";
        bar.style.right = "0";
        bar.style.zIndex = "40";
      } else {
        bar.style.position = "";
        bar.style.top = "";
        bar.style.left = "";
        bar.style.right = "";
      }
    };
    vv.addEventListener("resize", reposition);
    vv.addEventListener("scroll", reposition);
    return () => {
      vv.removeEventListener("resize", reposition);
      vv.removeEventListener("scroll", reposition);
    };
  }, [editor]);

  if (note.isLoading || !editor) {
    return <div className="viewer-splash">Loading notes…</div>;
  }

  const btn = (active: boolean) => `toolbar-btn${active ? " active" : ""}`;

  return (
    <div className="notes-tab">
      <div className="note-toolbar" ref={toolbarRef}>
        <button
          className={btn(editor.isActive("bold"))}
          onClick={() => editor.chain().focus().toggleBold().run()}
          aria-label="Bold"
        >
          <Bold size={16} strokeWidth={1.75} />
        </button>
        <button
          className={btn(editor.isActive("italic"))}
          onClick={() => editor.chain().focus().toggleItalic().run()}
          aria-label="Italic"
        >
          <Italic size={16} strokeWidth={1.75} />
        </button>
        <button
          className={btn(editor.isActive("strike"))}
          onClick={() => editor.chain().focus().toggleStrike().run()}
          aria-label="Strikethrough"
        >
          <Strikethrough size={16} strokeWidth={1.75} />
        </button>
        <span className="toolbar-sep" />
        <button
          className={btn(editor.isActive("heading", { level: 1 }))}
          onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
          aria-label="Heading 1"
        >
          <Heading1 size={16} strokeWidth={1.75} />
        </button>
        <button
          className={btn(editor.isActive("heading", { level: 2 }))}
          onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
          aria-label="Heading 2"
        >
          <Heading2 size={16} strokeWidth={1.75} />
        </button>
        <span className="toolbar-sep" />
        <button
          className={btn(editor.isActive("bulletList"))}
          onClick={() => editor.chain().focus().toggleBulletList().run()}
          aria-label="Bullet list"
        >
          <List size={16} strokeWidth={1.75} />
        </button>
        <button
          className={btn(editor.isActive("orderedList"))}
          onClick={() => editor.chain().focus().toggleOrderedList().run()}
          aria-label="Numbered list"
        >
          <ListOrdered size={16} strokeWidth={1.75} />
        </button>
        <button
          className={btn(editor.isActive("taskList"))}
          onClick={() => editor.chain().focus().toggleTaskList().run()}
          aria-label="Checklist"
        >
          <CheckSquare size={16} strokeWidth={1.75} />
        </button>
        <span className="toolbar-sep" />
        <button
          className={btn(editor.isActive("blockquote"))}
          onClick={() => editor.chain().focus().toggleBlockquote().run()}
          aria-label="Quote"
        >
          <Quote size={16} strokeWidth={1.75} />
        </button>
        <button
          className={btn(editor.isActive("codeBlock"))}
          onClick={() => editor.chain().focus().toggleCodeBlock().run()}
          aria-label="Code block"
        >
          <Code size={16} strokeWidth={1.75} />
        </button>
        <button
          className="toolbar-btn"
          onClick={() =>
            editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()
          }
          aria-label="Insert table"
        >
          <TableIcon size={16} strokeWidth={1.75} />
        </button>
        <span className="toolbar-sep" />
        <button
          className="toolbar-btn"
          onClick={() => editor.chain().focus().undo().run()}
          aria-label="Undo"
        >
          <Undo2 size={16} strokeWidth={1.75} />
        </button>
        <button
          className="toolbar-btn"
          onClick={() => editor.chain().focus().redo().run()}
          aria-label="Redo"
        >
          <Redo2 size={16} strokeWidth={1.75} />
        </button>
        <span className="toolbar-sep" />
        <button
          className="toolbar-btn"
          onClick={() => bumpFontSize(-1)}
          aria-label="Smaller text"
        >
          <AArrowDown size={16} strokeWidth={1.75} />
        </button>
        <button
          className="toolbar-btn"
          onClick={() => bumpFontSize(1)}
          aria-label="Larger text"
        >
          <AArrowUp size={16} strokeWidth={1.75} />
        </button>
        <span className="tint-row" role="group" aria-label="Page color">
          {TINTS.map((t) => (
            <button
              key={t.value}
              className={`tint-swatch${tint === t.value ? " selected" : ""}`}
              style={{ background: t.value }}
              onClick={() => pickTint(t.value)}
              aria-label={`${t.name} page`}
              title={t.name}
            />
          ))}
        </span>
        <a
          className="toolbar-btn"
          href={`/api/modules/${moduleId}/note/export`}
          aria-label="Export to Word"
          title="Export to Word (.docx)"
        >
          <FileDown size={16} strokeWidth={1.75} />
        </a>
        <span className={`save-state ${saveState}`}>
          {saveState === "saving" && "saving…"}
          {saveState === "saved" && "saved ✓"}
          {saveState === "error" && "not saved — check connection"}
        </span>
      </div>

      <div
        className="note-sheet"
        style={{ background: tint, ["--note-font-size" as string]: `${fontSize}px` }}
      >
        <EditorContent editor={editor} className="note-editor" />
      </div>
    </div>
  );
}
