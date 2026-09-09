import { describe, expect, it } from "vitest";

import { fmtPercent, fmtQpi, fmtScore, fmtUnits, targetSentence, weightWarning } from "./grades";

describe("fmtPercent", () => {
  it("keeps one decimal and drops a trailing zero", () => {
    expect(fmtPercent(91.64)).toBe("91.6%");
    expect(fmtPercent(90)).toBe("90%");
    expect(fmtPercent(87.75)).toBe("87.8%");
    expect(fmtPercent(104)).toBe("104%"); // extra credit is never capped
  });

  it("shows an em dash when there is nothing yet", () => {
    expect(fmtPercent(null)).toBe("—");
    expect(fmtPercent(undefined)).toBe("—");
  });
});

describe("fmtQpi", () => {
  it("always reads with two decimals", () => {
    expect(fmtQpi(3.25)).toBe("3.25");
    expect(fmtQpi(4)).toBe("4.00");
    expect(fmtQpi(null)).toBe("—");
  });
});

describe("fmtUnits", () => {
  it("pluralises and trims", () => {
    expect(fmtUnits(3)).toBe("3 units");
    expect(fmtUnits(1)).toBe("1 unit");
    expect(fmtUnits(1.5)).toBe("1.5 units");
  });
});

describe("fmtScore", () => {
  it("shows points, percentages and the ungraded placeholder", () => {
    expect(fmtScore({ earned: 9.01, possible: 10.01, percent: null, graded: true })).toBe(
      "9.01 / 10.01",
    );
    expect(fmtScore({ earned: 100, possible: 100, percent: null, graded: true })).toBe("100 / 100");
    expect(fmtScore({ earned: null, possible: null, percent: 95, graded: true })).toBe("95%");
    expect(fmtScore({ earned: null, possible: 130, percent: null, graded: false })).toBe(
      "not graded yet",
    );
  });
});

describe("targetSentence", () => {
  it("states what the remaining weight must average", () => {
    expect(
      targetSentence({ letter: "B+", cutoff: 88, needed: 89, reachable: true }, 20),
    ).toBe("To finish with B+ you need 89% on the remaining 20%.");
  });

  it("calls out an unreachable target", () => {
    expect(targetSentence({ letter: "A", cutoff: 93, needed: 114, reachable: false }, 20)).toBe(
      "A is out of reach — it would need 114% of the remaining 20%.",
    );
  });

  it("calls out a secured target", () => {
    expect(targetSentence({ letter: "C", cutoff: 73, needed: -5, reachable: true }, 20)).toBe(
      "C is already secured.",
    );
  });
});

describe("weightWarning", () => {
  it("is silent at exactly 100 and while empty", () => {
    expect(weightWarning(100)).toBeNull();
    expect(weightWarning(0)).toBeNull();
  });

  it("names what is missing or excessive", () => {
    expect(weightWarning(80)).toBe(
      "Weights add up to 80% — 20% of the syllabus is missing.",
    );
    expect(weightWarning(110)).toBe("Weights add up to 110% — more than a whole grade.");
  });
});
