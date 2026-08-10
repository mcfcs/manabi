import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Image as TiptapImage } from "@tiptap/extension-image";
import { Mathematics } from "@tiptap/extension-mathematics";
import { Table } from "@tiptap/extension-table";
import { TableCell } from "@tiptap/extension-table-cell";
import { TableHeader } from "@tiptap/extension-table-header";
import { TableRow } from "@tiptap/extension-table-row";
import { TaskItem } from "@tiptap/extension-task-item";
import { TaskList } from "@tiptap/extension-task-list";
import { EditorContent, useEditor, type Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import "katex/dist/katex.min.css";
import {
  AArrowDown,
  AArrowUp,
  Bold,
  CheckSquare,
  ChevronDown,
  ChevronUp,
  Code,
  FileDown,
  FilePlus2,
  Heading1,
  Heading2,
  ImagePlus,
  Italic,
  List,
  ListOrdered,
  Quote,
  Redo2,
  Strikethrough,
  Table as TableIcon,
  Trash2,
  Undo2,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, type NoteListItem, type NoteOut } from "../../lib/api";
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

async function uploadImage(noteId: number, file: File): Promise<string> {
  const form = new FormData();
  form.append("file", file);
  const r = await api.postForm<{ url: string }>(`/api/notes/${noteId}/images`, form);
  return r.url;
}

function insertImageFiles(editor: Editor, noteId: number, files: File[]): boolean {
  const images = files.filter((f) => f.type.startsWith("image/"));
  if (images.length === 0) return false;
  for (const file of images) {
    uploadImage(noteId, file)
      .then((url) =>
        editor.chain().focus().insertContent({ type: "image", attrs: { src: url } }).run(),
      )
      .catch(() => undefined);
  }
  return true;
}

/** Sidebar of note sections — Google-Docs-style: create, rename (double-
 * click), reorder (arrows), delete. Collapses to a chip strip on mobile. */
function NoteSidebar({
  moduleId,
  notes,
  activeId,
  onSelect,
}: {
  moduleId: string;
  notes: NoteListItem[];
  activeId: number | null;
  onSelect: (id: number) => void;
}) {
  const queryClient = useQueryClient();
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameText, setRenameText] = useState("");
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["notes", moduleId] });

  const create = useMutation({
    mutationFn: () =>
      api.post<NoteOut>(`/api/modules/${moduleId}/notes`, { title: "Untitled" }),
    onSuccess: (n) => {
      invalidate();
      onSelect(n.id);
      setRenamingId(n.id);
      setRenameText(n.title);
    },
  });
  const rename = useMutation({
    mutationFn: ({ id, title }: { id: number; title: string }) =>
      api.patch<NoteOut>(`/api/notes/${id}`, { title }),
    onSuccess: invalidate,
  });
  const reorder = useMutation({
    mutationFn: (updates: { id: number; position: number }[]) =>
      Promise.all(
        updates.map((u) => api.patch(`/api/notes/${u.id}`, { position: u.position })),
      ),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/api/notes/${id}`),
    onSuccess: (_r, id) => {
      invalidate();
      if (id === activeId) {
        const rest = notes.filter((n) => n.id !== id);
        if (rest.length > 0) onSelect(rest[0].id);
      }
    },
  });

  function move(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= notes.length) return;
    const order = [...notes];
    [order[index], order[target]] = [order[target], order[index]];
    reorder.mutate(order.map((n, i) => ({ id: n.id, position: i })));
  }

  function commitRename(id: number) {
    const title = renameText.trim();
    setRenamingId(null);
    if (title) rename.mutate({ id, title });
  }

  return (
    <aside className="note-sidebar">
      <div className="note-sidebar-head">
        <span className="note-sidebar-label">Sections</span>
        <button
          className="icon-btn"
          onClick={() => create.mutate()}
          aria-label="New note"
          title="New note"
        >
          <FilePlus2 size={15} strokeWidth={1.5} />
        </button>
      </div>
      <div className="note-sidebar-list">
        {notes.map((n, i) => (
          <div
            key={n.id}
            className={`note-sidebar-item${n.id === activeId ? " active" : ""}`}
          >
            {renamingId === n.id ? (
              <input
                className="input note-rename-input"
                value={renameText}
                autoFocus
                onChange={(e) => setRenameText(e.target.value)}
                onBlur={() => commitRename(n.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitRename(n.id);
                  if (e.key === "Escape") setRenamingId(null);
                }}
              />
            ) : (
              <button
                className="note-sidebar-title"
                onClick={() => onSelect(n.id)}
                onDoubleClick={() => {
                  setRenamingId(n.id);
                  setRenameText(n.title);
                }}
                title={`${n.title} — double-click to rename`}
              >
                {n.title}
              </button>
            )}
            <span className="note-sidebar-actions">
              <button
                className="icon-btn"
                onClick={() => move(i, -1)}
                disabled={i === 0}
                aria-label="Move up"
              >
                <ChevronUp size={13} strokeWidth={1.5} />
              </button>
              <button
                className="icon-btn"
                onClick={() => move(i, 1)}
                disabled={i === notes.length - 1}
                aria-label="Move down"
              >
                <ChevronDown size={13} strokeWidth={1.5} />
              </button>
              <button
                className="icon-btn danger"
                onClick={() => {
                  if (window.confirm(`Delete "${n.title}"? This cannot be undone.`))
                    remove.mutate(n.id);
                }}
                disabled={notes.length <= 1}
                aria-label="Delete note"
              >
                <Trash2 size={13} strokeWidth={1.5} />
              </button>
            </span>
          </div>
        ))}
      </div>
    </aside>
  );
}

export function NotesTab({
  moduleId,
  initialNoteId,
}: {
  moduleId: string;
  initialNoteId?: number;
}) {
  const queryClient = useQueryClient();
  const [activeId, setActiveId] = useState<number | null>(initialNoteId ?? null);

  const notes = useQuery({
    queryKey: ["notes", moduleId],
    queryFn: () => api.get<NoteListItem[]>(`/api/modules/${moduleId}/notes`),
  });

  // First visit to a module with zero notes: create the initial section once.
  const creatingRef = useRef(false);
  useEffect(() => {
    if (!notes.data) return;
    if (notes.data.length === 0 && !creatingRef.current) {
      creatingRef.current = true;
      api
        .post<NoteOut>(`/api/modules/${moduleId}/notes`, { title: "Notes" })
        .then((n) => {
          queryClient.invalidateQueries({ queryKey: ["notes", moduleId] });
          setActiveId(n.id);
        })
        .finally(() => {
          creatingRef.current = false;
        });
      return;
    }
    if (activeId === null || !notes.data.some((n) => n.id === activeId)) {
      if (notes.data.length > 0) setActiveId(notes.data[0].id);
    }
  }, [notes.data, activeId, moduleId, queryClient]);

  if (notes.isLoading || activeId === null) {
    return <div className="viewer-splash">Loading notes…</div>;
  }

  return (
    <div className="notes-tab">
      <NoteSidebar
        moduleId={moduleId}
        notes={notes.data ?? []}
        activeId={activeId}
        onSelect={setActiveId}
      />
      {/* key remounts the editor per note: its pending autosave buffer and
          save closure are bound to one note id, so a flush can never write
          one note's content into another */}
      <NoteEditor key={activeId} noteId={activeId} />
    </div>
  );
}

function NoteEditor({ noteId }: { noteId: number }) {
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
  const fileInputRef = useRef<HTMLInputElement>(null);

  const note = useQuery({
    queryKey: ["note", noteId],
    queryFn: () => api.get<NoteOut>(`/api/notes/${noteId}`),
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
          `/api/notes/${noteId}`,
          { pm_json: pmJson },
          { keepalive: true },
        );
        // Keep the cache mirroring the server — otherwise returning to this
        // tab re-initializes the editor from a stale pre-save snapshot
        // (and typing into that would overwrite the real note).
        queryClient.setQueryData(["note", noteId], saved);
        pendingRef.current = null;
        setSaveState("saved");
      } catch {
        setSaveState("error");
      }
    },
    [noteId, queryClient],
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
        TiptapImage,
      ],
      content: note.data?.pm_json ?? "",
      editorProps: {
        attributes: { class: "note-editor-content", spellcheck: "true" },
        handlePaste: (_view, event) => {
          const files = Array.from(event.clipboardData?.files ?? []);
          if (editor && insertImageFiles(editor, noteId, files)) {
            event.preventDefault();
            return true;
          }
          return false;
        },
        handleDrop: (_view, event) => {
          const files = Array.from(event.dataTransfer?.files ?? []);
          if (editor && insertImageFiles(editor, noteId, files)) {
            event.preventDefault();
            return true;
          }
          return false;
        },
      },
      onUpdate: ({ editor }) => {
        pendingRef.current = editor.getJSON() as Record<string, unknown>;
        if (debounceRef.current) window.clearTimeout(debounceRef.current);
        debounceRef.current = window.setTimeout(() => {
          if (pendingRef.current) save(pendingRef.current);
        }, 800);
      },
    },
    [noteId, note.data != null],
  );

  // Flush unsaved changes when leaving / backgrounding / switching notes
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
    <div className="note-pane">
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
        <button
          className="toolbar-btn"
          onClick={() => fileInputRef.current?.click()}
          aria-label="Insert image"
          title="Insert image"
        >
          <ImagePlus size={16} strokeWidth={1.75} />
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/png,image/jpeg,image/gif,image/webp"
          hidden
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            if (files.length > 0) insertImageFiles(editor, noteId, files);
            e.target.value = "";
          }}
        />
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
          href={`/api/notes/${noteId}/export`}
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
