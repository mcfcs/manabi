import { describe, expect, it } from "vitest";

import { type CanvasCourse, normalizeCode, suggestCanvasCourse } from "./canvasMatch";

const list: CanvasCourse[] = [
  { id: 1, name: "Structure and Interpretation", course_code: "CSCI 70" },
  { id: 2, name: "Social Computing", course_code: "CSCI 161" },
  { id: 3, name: "Networks", course_code: "CSCI-60_A" },
  { id: 4, name: "Untitled", course_code: null },
  { id: 5, name: "Politics", course_code: "SocSc 14" },
  { id: 6, name: "Politics (other section)", course_code: "SocSc 14" },
];

describe("normalizeCode", () => {
  it("keeps only lowercase alphanumerics", () => {
    expect(normalizeCode("CSCI 142i")).toBe("csci142i");
    expect(normalizeCode("ISCS 30.18")).toBe("iscs3018");
    expect(normalizeCode("CSCI-60_A")).toBe("csci60a");
  });
});

describe("suggestCanvasCourse", () => {
  it("returns the exact normalized match", () => {
    expect(suggestCanvasCourse("csci 70", list)?.id).toBe(1);
  });

  it("matches when one code is a prefix of the other", () => {
    expect(suggestCanvasCourse("CSCI 161.03", list)?.id).toBe(2);
    expect(suggestCanvasCourse("CSCI 60", list)?.id).toBe(3);
  });

  it("never guesses when the match is ambiguous or absent", () => {
    expect(suggestCanvasCourse("SocSc 14", list)).toBeNull();
    expect(suggestCanvasCourse("MATH 199", list)).toBeNull();
    expect(suggestCanvasCourse("CS", list)).toBeNull();
    expect(suggestCanvasCourse("", list)).toBeNull();
  });

  it("ignores Canvas courses without a code", () => {
    expect(suggestCanvasCourse("Untitled", list)).toBeNull();
  });
});
