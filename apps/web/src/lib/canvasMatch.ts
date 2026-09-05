/** Matching a Manabi course to one of the user's Canvas courses by code. */

export interface CanvasCourse {
  id: number;
  name: string;
  course_code: string | null;
}

/** Lowercase alphanumerics only: "CSCI 142i" → "csci142i". */
export function normalizeCode(code: string): string {
  return code.toLowerCase().replace(/[^a-z0-9]/g, "");
}

/**
 * The single Canvas course whose code matches the Manabi code: an exact
 * normalized match wins; otherwise one code must be a prefix of the other
 * ("CSCI 161.03" ↔ "CSCI 161"). Ambiguous or empty → null, never a guess.
 */
export function suggestCanvasCourse(
  code: string,
  courses: readonly CanvasCourse[],
): CanvasCourse | null {
  const key = normalizeCode(code);
  if (key.length < 3) return null;
  const exact = courses.filter((c) => normalizeCode(c.course_code ?? "") === key);
  if (exact.length === 1) return exact[0];
  if (exact.length > 1) return null;
  const prefix = courses.filter((c) => {
    const k = normalizeCode(c.course_code ?? "");
    return k.length >= 3 && (k.startsWith(key) || key.startsWith(k));
  });
  return prefix.length === 1 ? prefix[0] : null;
}
