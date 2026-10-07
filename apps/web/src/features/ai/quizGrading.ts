import type { QuestionOut } from "../../lib/api";

// Client-side answer matching, shared by the quiz player and the exam player.
// Deliberately lenient for prose (an override link is the escape hatch for
// wording edge cases); exact for printed output when the code was run.

export const norm = (s: string) =>
  s
    .toLowerCase()
    .normalize("NFKC")
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();

export function fuzzyEqual(a: string, b: string): boolean {
  const na = norm(a);
  const nb = norm(b);
  if (!na || !nb) return false;
  if (na === nb || na.includes(nb) || nb.includes(na)) return true;
  const ta = na.split(" ");
  const tb = new Set(nb.split(" "));
  const overlap = ta.filter((t) => tb.has(t)).length;
  return overlap / Math.max(ta.length, tb.size) >= 0.6;
}

/** Exact-output compare: CRLF-safe, trailing spaces and blank lines ignored. */
export const normOutput = (s: string) =>
  s
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((l) => l.trimEnd())
    .join("\n")
    .replace(/\n+$/, "")
    .trim();

/** Greedy 1:1 match of the student's lines against the answer items. */
export function matchEnumeration(userLines: string[], items: string[]): boolean[] {
  const remaining = userLines.filter((l) => l.trim());
  return items.map((item) => {
    const i = remaining.findIndex((l) => fuzzyEqual(l, item));
    if (i === -1) return false;
    remaining.splice(i, 1);
    return true;
  });
}

export type Grade = "right" | "wrong" | "self";

/** Grade one response. "self" = the student must judge it (essay, coding,
 * unverified output). An empty response is always wrong. */
export function gradeResponse(q: QuestionOut, response: string | undefined): Grade {
  const r = (response ?? "").trim();
  const a = q.answer;
  if (a.kind === "essay" || a.kind === "coding") return r ? "self" : "wrong";
  if (!r) return "wrong";
  switch (a.kind) {
    case "mcq":
      return Number(r) === a.correct_option ? "right" : "wrong";
    case "tf":
      return (r === "true") === a.value ? "right" : "wrong";
    case "output":
      if (normOutput(r) === normOutput(a.text)) return "right";
      // Only call it wrong when the key was produced by running the code.
      return a.verified === "executed" ? "wrong" : "self";
    case "identification":
    case "short":
      return fuzzyEqual(r, a.text) ? "right" : "wrong";
    case "enumeration":
      return matchEnumeration(r.split("\n"), a.items).every(Boolean) ? "right" : "wrong";
  }
  return "self";
}

/** The correct answer as text, for review screens. */
export function answerText(q: QuestionOut): string {
  const a = q.answer;
  switch (a.kind) {
    case "mcq":
      return q.options?.[a.correct_option] ?? `Option ${a.correct_option + 1}`;
    case "tf":
      return a.value ? "True" : "False";
    case "enumeration":
      return a.items.join("\n");
    case "essay":
      return a.model_answer;
    case "coding":
      return a.solution;
    default:
      return a.text;
  }
}

/** The student's response as text, for review screens. */
export function responseText(q: QuestionOut, response: string | undefined): string {
  if (!response) return "";
  if (q.qtype === "mcq") return q.options?.[Number(response)] ?? "";
  if (q.qtype === "tf") return response === "true" ? "True" : "False";
  return response;
}
