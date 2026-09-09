/** Formatting helpers for grade figures. All arithmetic lives on the server
 * (manabi_server.grades) so there is a single source of truth; this file only
 * turns numbers into the strings the UI shows. */

/** "91.6%" — one decimal, trailing ".0" dropped. `null` becomes an em dash. */
export function fmtPercent(value: number | null | undefined): string {
  if (value == null) return "—";
  const rounded = Math.round(value * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded : rounded.toFixed(1)}%`;
}

/** "3.25" — QPI always reads with two decimals. */
export function fmtQpi(value: number | null | undefined): string {
  return value == null ? "—" : value.toFixed(2);
}

/** "3 units" / "1.5 units" */
export function fmtUnits(units: number): string {
  const n = Number.isInteger(units) ? units : Number(units.toFixed(1));
  return `${n} unit${n === 1 ? "" : "s"}`;
}

/** A score row as the reader sees it: points, a percentage, or a placeholder. */
export function fmtScore(item: {
  earned: number | null;
  possible: number | null;
  percent: number | null;
  graded: boolean;
}): string {
  if (!item.graded) return "not graded yet";
  if (item.percent != null) return fmtPercent(item.percent);
  const earned = item.earned ?? 0;
  const possible = item.possible ?? 0;
  const trim = (n: number) => (Number.isInteger(n) ? String(n) : String(Number(n.toFixed(2))));
  return `${trim(earned)} / ${trim(possible)}`;
}

/** The sentence under the standing: what the untouched weight must average. */
export function targetSentence(target: {
  letter: string;
  cutoff: number;
  needed: number;
  reachable: boolean;
}, remainingWeight: number): string {
  const need = fmtPercent(target.needed);
  const rest = fmtPercent(remainingWeight);
  if (!target.reachable) {
    return `${target.letter} is out of reach — it would need ${need} of the remaining ${rest}.`;
  }
  if (target.needed <= 0) {
    return `${target.letter} is already secured.`;
  }
  return `To finish with ${target.letter} you need ${need} on the remaining ${rest}.`;
}

/** Weights should normally total 100; say so when they don't. */
export function weightWarning(total: number): string | null {
  if (total === 0) return null;
  const rounded = Math.round(total * 100) / 100;
  if (rounded === 100) return null;
  return rounded > 100
    ? `Weights add up to ${fmtPercent(rounded)} — more than a whole grade.`
    : `Weights add up to ${fmtPercent(rounded)} — ${fmtPercent(100 - rounded)} of the syllabus is missing.`;
}
