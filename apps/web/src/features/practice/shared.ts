import type {
  PracticeKind,
  PracticeLanguage,
  PracticeStatus,
  ProblemOut,
} from "../../lib/api";

export const KIND_LABEL: Record<PracticeKind, string> = {
  code: "Code",
  grammar: "Grammar",
  regex: "Regex",
  dfa: "DFA",
};

export const LANG_LABEL: Record<PracticeLanguage, string> = {
  c: "C",
  cpp: "C++",
  python: "Python",
};

export const LANGS: PracticeLanguage[] = ["c", "cpp", "python"];

/** The course style: Allman braces, three-space indent. */
export const TEMPLATES: Record<PracticeLanguage, string> = {
  c: "#include <stdio.h>\n\nint main()\n{\n   \n   return 0;\n}\n",
  cpp: "#include <iostream>\nusing namespace std;\n\nint main()\n{\n   \n   return 0;\n}\n",
  python: "",
};

export const INDENT = "   ";

export function isActive(status: PracticeStatus): boolean {
  return status === "generating" || status === "validating";
}

const VERDICT_LABEL: Record<string, string> = {
  accepted: "Accepted",
  passed: "Passed",
  wrong: "Wrong answer",
  compile_error: "Compile error",
  runtime_error: "Runtime error",
  time_limit: "Time limit exceeded",
  no_tests: "No tests",
  format_error: "Format error",
};

export function verdictLabel(v: string): string {
  return VERDICT_LABEL[v] ?? v.replace(/_/g, " ");
}

/** Tone class for a verdict: ok (green), bad (red), warn (amber), muted. */
export function verdictTone(v: string): "ok" | "bad" | "warn" | "muted" {
  if (v === "accepted" || v === "passed") return "ok";
  if (v === "wrong" || v === "runtime_error") return "bad";
  if (v === "compile_error" || v === "time_limit" || v === "format_error") return "warn";
  return "muted";
}

/** A theory string for display: the empty string reads as ε. */
export function showString(s: string): string {
  return s === "" ? "ε" : s;
}

/** Spec fields are AI-written: accept a string, a list, or nothing. */
export function asText(v: unknown): string {
  if (v == null) return "";
  if (Array.isArray(v)) return v.map((x) => `- ${String(x)}`).join("\n");
  return String(v);
}

/** localStorage slot for a draft: one per problem and language (or kind). */
export function draftKey(problemId: number, slot: string): string {
  return `manabi-practice-draft-${problemId}-${slot}`;
}

export function loadDraft(problemId: number, slot: string): string | null {
  try {
    return localStorage.getItem(draftKey(problemId, slot));
  } catch {
    return null;
  }
}

export function saveDraft(problemId: number, slot: string, text: string): void {
  try {
    localStorage.setItem(draftKey(problemId, slot), text);
  } catch {
    /* storage full or blocked — the draft just isn't remembered */
  }
}

/** What the editor starts with for a language: the saved draft, else the
 * problem's starter code in its own language, else the bare template. */
export function initialCode(problem: Pick<ProblemOut, "id" | "language" | "spec">, lang: PracticeLanguage): string {
  const saved = loadDraft(problem.id, lang);
  if (saved != null) return saved;
  const starter = typeof problem.spec?.starter_code === "string" ? problem.spec.starter_code : "";
  if (lang === problem.language && starter.trim()) return starter;
  return TEMPLATES[lang];
}

export function timeAgo(iso: string, now = Date.now()): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  if (d < 7) return `${d} d ago`;
  return new Date(iso).toLocaleDateString();
}
