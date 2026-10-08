import { beforeEach, describe, expect, it, vi } from "vitest";

import { asText, initialCode, saveDraft, showString, TEMPLATES, verdictTone } from "./shared";

const problem = {
  id: 7,
  language: "cpp" as const,
  spec: { starter_code: "#include <iostream>\nint main() {}\n" },
};

describe("practice drafts", () => {
  // Node's own (file-less) localStorage can shadow jsdom's; use a plain map.
  beforeEach(() => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
      clear: () => store.clear(),
    });
  });

  it("starts the problem's own language from its starter code", () => {
    expect(initialCode(problem, "cpp")).toBe(problem.spec.starter_code);
  });

  it("starts other languages from the course-style template", () => {
    expect(initialCode(problem, "c")).toBe(TEMPLATES.c);
    expect(TEMPLATES.c).toContain("int main()\n{\n   \n   return 0;\n}");
    expect(initialCode(problem, "python")).toBe("");
  });

  it("prefers a saved draft, per language", () => {
    saveDraft(7, "c", "int x;");
    expect(initialCode(problem, "c")).toBe("int x;");
    expect(initialCode(problem, "cpp")).toBe(problem.spec.starter_code);
  });

  it("falls back to the template when the starter code is blank", () => {
    expect(initialCode({ ...problem, spec: { starter_code: "  " } }, "cpp")).toBe(TEMPLATES.cpp);
  });
});

describe("practice display helpers", () => {
  it("shows the empty string as ε", () => {
    expect(showString("")).toBe("ε");
    expect(showString("ab")).toBe("ab");
  });

  it("reads spec fields written as a list", () => {
    expect(asText(["1 ≤ n ≤ 100", "n is even"])).toBe("- 1 ≤ n ≤ 100\n- n is even");
    expect(asText(undefined)).toBe("");
  });

  it("colours verdicts", () => {
    expect(verdictTone("accepted")).toBe("ok");
    expect(verdictTone("wrong")).toBe("bad");
    expect(verdictTone("compile_error")).toBe("warn");
    expect(verdictTone("no_tests")).toBe("muted");
  });
});
