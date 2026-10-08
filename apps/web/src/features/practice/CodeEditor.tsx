/* CodeMirror 6 editor for the practice page. Loaded with React.lazy so the
   editor and its language packs are a separate chunk. */
import { cpp } from "@codemirror/lang-cpp";
import { python } from "@codemirror/lang-python";
import { HighlightStyle, indentUnit, syntaxHighlighting } from "@codemirror/language";
import { Compartment, EditorSelection, EditorState, Prec } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { indentLess, indentMore } from "@codemirror/commands";
import { tags as t } from "@lezer/highlight";
import { basicSetup } from "codemirror";
import { useEffect, useRef } from "react";

import type { PracticeLanguage } from "../../lib/api";
import { INDENT } from "./shared";

const theme = EditorView.theme({
  "&": {
    backgroundColor: "var(--surface-raised)",
    color: "var(--ink)",
    fontSize: "13.5px",
    height: "100%",
  },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": {
    fontFamily: "var(--font-mono)",
    lineHeight: "1.55",
  },
  ".cm-content": { caretColor: "var(--ink)", padding: "10px 0" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--ink)" },
  "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, ::selection":
    { backgroundColor: "var(--accent-blue-wash)" },
  ".cm-gutters": {
    backgroundColor: "var(--surface)",
    color: "var(--ink-faint)",
    border: "none",
    borderRight: "1px solid var(--rule)",
  },
  ".cm-activeLine": { backgroundColor: "rgba(28, 36, 52, 0.035)" },
  ".cm-activeLineGutter": { backgroundColor: "rgba(28, 36, 52, 0.06)", color: "var(--ink-soft)" },
  ".cm-matchingBracket, &.cm-focused .cm-matchingBracket": {
    backgroundColor: "var(--accent-blue-wash)",
    outline: "1px solid rgba(40, 81, 143, 0.35)",
  },
  ".cm-foldPlaceholder": {
    backgroundColor: "var(--surface)",
    border: "1px solid var(--rule)",
    color: "var(--ink-soft)",
  },
  ".cm-tooltip": {
    backgroundColor: "var(--surface-raised)",
    border: "1px solid var(--rule)",
    borderRadius: "var(--radius-sm)",
  },
  ".cm-tooltip-autocomplete > ul > li[aria-selected]": {
    backgroundColor: "var(--accent-blue-wash)",
    color: "var(--accent-blue-deep)",
  },
  ".cm-panels": { backgroundColor: "var(--surface)", color: "var(--ink)" },
});

// The notebook palette: blue ink for structure, red pen for literals.
const highlight = HighlightStyle.define([
  { tag: [t.keyword, t.controlKeyword, t.moduleKeyword, t.operatorKeyword], color: "#1e4076", fontWeight: "600" },
  { tag: [t.typeName, t.standard(t.typeName)], color: "#28518f" },
  { tag: [t.definition(t.variableName), t.function(t.variableName)], color: "#1c2434", fontWeight: "600" },
  { tag: [t.string, t.special(t.string), t.character], color: "#3e7a4e" },
  { tag: [t.number, t.bool, t.null, t.atom], color: "#a92e24" },
  { tag: [t.comment, t.lineComment, t.blockComment], color: "#8b92a3", fontStyle: "italic" },
  { tag: [t.processingInstruction, t.meta], color: "#b07d1f" },
  { tag: [t.operator, t.punctuation, t.bracket], color: "#4c556a" },
]);

function languageExt(lang: PracticeLanguage | null) {
  if (lang === "python") return python();
  if (lang === "c" || lang === "cpp") return cpp();
  return [];
}

export default function CodeEditor({
  value,
  onChange,
  language,
  onRun,
  ariaLabel,
  compact = false,
}: {
  value: string;
  onChange: (v: string) => void;
  /** null = plain text (grammar / regex / DFA answers) */
  language: PracticeLanguage | null;
  onRun: () => void;
  ariaLabel: string;
  /** a shorter box, for one-to-ten-line theory answers */
  compact?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const langComp = useRef(new Compartment());
  const cb = useRef({ onChange, onRun });
  cb.current = { onChange, onRun };

  useEffect(() => {
    if (!host.current) return;
    const v = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          Prec.highest(
            keymap.of([
              {
                key: "Mod-Enter",
                run: () => {
                  cb.current.onRun();
                  return true;
                },
              },
              {
                // Tab inserts three spaces (the course style); with a
                // selection it indents the selected lines instead.
                key: "Tab",
                run: (view) => {
                  if (view.state.selection.ranges.some((r) => !r.empty)) return indentMore(view);
                  view.dispatch(
                    view.state.changeByRange((r) => ({
                      changes: { from: r.from, insert: INDENT },
                      range: EditorSelection.cursor(r.from + INDENT.length),
                    })),
                  );
                  return true;
                },
                shift: indentLess,
              },
            ]),
          ),
          basicSetup,
          indentUnit.of(INDENT),
          EditorState.tabSize.of(3),
          theme,
          syntaxHighlighting(highlight),
          langComp.current.of(languageExt(language)),
          EditorView.contentAttributes.of({ "aria-label": ariaLabel }),
          EditorView.updateListener.of((u) => {
            if (u.docChanged) cb.current.onChange(u.state.doc.toString());
          }),
        ],
      }),
    });
    view.current = v;
    return () => {
      v.destroy();
      view.current = null;
    };
    // Built once; value / language changes are applied below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // External replacement (language switch, loading an old submission).
  useEffect(() => {
    const v = view.current;
    if (!v) return;
    const cur = v.state.doc.toString();
    if (cur !== value) {
      v.dispatch({ changes: { from: 0, to: cur.length, insert: value } });
    }
  }, [value]);

  useEffect(() => {
    view.current?.dispatch({ effects: langComp.current.reconfigure(languageExt(language)) });
  }, [language]);

  return <div ref={host} className={`practice-cm${compact ? " compact" : ""}`} />;
}
