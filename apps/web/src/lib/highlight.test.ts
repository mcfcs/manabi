import { describe, expect, it } from "vitest";

import {
  type AnnotationMark,
  applyHighlights,
  clearHighlights,
  countTermsPresent,
  highlightHtml,
} from "./highlight";

function root(html: string): HTMLElement {
  const el = document.createElement("div");
  el.className = "viewer-text-content";
  el.innerHTML = html;
  return el;
}

describe("applyHighlights — terms", () => {
  it("wraps whole-word matches only", () => {
    const el = root("<p>Signal attenuation grows.</p>");
    applyHighlights(el, ["attenuation"], []);
    const marks = el.querySelectorAll("mark.term-mark");
    expect(marks).toHaveLength(1);
    expect(marks[0].textContent).toBe("attenuation");
  });

  it("does NOT match a term inside a larger word (IRRI ≠ irrigated)", () => {
    const el = root("<p>The NPA and IRRI worked on irrigated land.</p>");
    applyHighlights(el, ["IRRI", "NPA"], []);
    const marks = [...el.querySelectorAll("mark.term-mark")].map((m) => m.textContent);
    // NPA + the standalone IRRI, but NOT the "irri" inside "irrigated"
    expect(marks).toEqual(["NPA", "IRRI"]);
    expect(el.innerHTML).toContain("irrigated");
    expect(el.querySelectorAll("mark").length).toBe(2);
  });

  it("matches a term that spans an inline <b> boundary", () => {
    const el = root("<p>the <b>New People</b>'s Army marched</p>");
    applyHighlights(el, ["New People's Army"], []);
    const marks = el.querySelectorAll("mark.term-mark");
    expect(marks.length).toBeGreaterThanOrEqual(1);
    // the full phrase is covered (possibly across wrapper fragments)
    const text = [...marks].map((m) => m.textContent).join("");
    expect(text.replace(/\s+/g, " ")).toContain("New People's Army");
  });

  it("does not match a term across a paragraph boundary", () => {
    const el = root("<p>alpha</p><p>beta</p>");
    applyHighlights(el, ["alphabeta"], []);
    expect(el.querySelectorAll("mark").length).toBe(0);
  });
});

describe("applyHighlights — annotations", () => {
  const yellow: AnnotationMark = {
    id: 7,
    quote: "time-division multiplexing",
    color: "yellow",
    hasNote: true,
  };

  it("wraps the quote in a clickable mark with id + color + note flag", () => {
    const el = root("<p>Uses time-division multiplexing here.</p>");
    applyHighlights(el, [], [yellow]);
    const mark = el.querySelector("mark.annot") as HTMLElement;
    expect(mark).toBeTruthy();
    expect(mark.dataset.annotIds).toBe("7");
    expect(mark.className).toContain("annot-yellow");
    expect(mark.className).toContain("has-note");
    expect(mark.textContent).toBe("time-division multiplexing");
  });

  it("marks only the first occurrence", () => {
    const el = root("<p>DS-1 and DS-1 again</p>");
    applyHighlights(el, [], [{ id: 1, quote: "DS-1", color: "blue", hasNote: false }]);
    expect(el.querySelectorAll("mark.annot").length).toBe(1);
  });

  it("matches a quote that spans a <b> and tolerates whitespace differences", () => {
    // stored quote has single spaces; DOM splits across a bold word + newline
    const el = root("<p>the villagers were\n   <b>united</b> only when threatened</p>");
    applyHighlights(el, [], [
      { id: 2, quote: "were united only", color: "green", hasNote: false },
    ]);
    const mark = el.querySelector("mark.annot");
    expect(mark).toBeTruthy();
    expect(mark!.textContent!.replace(/\s+/g, " ")).toBe("were united only");
  });

  it("tolerates HTML entities decoded in the DOM (it&#x27;s ↔ it's)", () => {
    const el = root("<p>it&#x27;s a fine day</p>");
    applyHighlights(el, [], [{ id: 3, quote: "it's a fine", color: "red", hasNote: false }]);
    expect(el.querySelector("mark.annot")?.textContent).toBe("it's a fine");
  });

  it("leaves the DOM unchanged when the quote no longer matches", () => {
    const el = root("<p>The text was edited.</p>");
    const before = el.innerHTML;
    applyHighlights(el, [], [{ id: 4, quote: "vanished sentence", color: "yellow", hasNote: false }]);
    expect(el.innerHTML).toBe(before);
  });
});

describe("applyHighlights — overlap + idempotency", () => {
  it("annotations win over terms on overlap", () => {
    const el = root("<p>study the attenuation curve</p>");
    applyHighlights(
      el,
      ["attenuation"],
      [{ id: 9, quote: "the attenuation curve", color: "yellow", hasNote: false }],
    );
    // the annotation covers 'attenuation', so no term-mark is emitted there
    expect(el.querySelectorAll("mark.term-mark").length).toBe(0);
    const annot = el.querySelector("mark.annot");
    expect(annot?.textContent).toBe("the attenuation curve");
  });

  it("renders TWO overlapping annotations, tagging the overlap with both ids", () => {
    // A = "the quick brown", B = "quick brown fox" → overlap on "quick brown"
    const el = root("<p>the quick brown fox jumps</p>");
    applyHighlights(el, [], [
      { id: 10, quote: "the quick brown", color: "yellow", hasNote: false },
      { id: 11, quote: "quick brown fox", color: "blue", hasNote: false },
    ]);
    const marks = [...el.querySelectorAll("mark.annot")] as HTMLElement[];
    // 3 flattened segments: "the " (10), "quick brown" (10+11), " fox" (11)
    expect(marks.length).toBe(3);
    const overlap = marks.find((m) => m.dataset.annotIds === "10,11");
    expect(overlap).toBeTruthy();
    expect(overlap!.className).toContain("annot-multi");
    expect(overlap!.textContent).toBe("quick brown");
    // both single-owner segments still exist
    expect(marks.some((m) => m.dataset.annotIds === "10")).toBe(true);
    expect(marks.some((m) => m.dataset.annotIds === "11")).toBe(true);
  });

  it("clearHighlights restores the original text; re-apply is stable", () => {
    const el = root("<p>Signal attenuation grows.</p>");
    const original = el.innerHTML;
    applyHighlights(el, ["attenuation"], []);
    clearHighlights(el);
    expect(el.innerHTML).toBe(original);
    // applyHighlights is itself idempotent (clears first)
    applyHighlights(el, ["attenuation"], []);
    applyHighlights(el, ["attenuation"], []);
    expect(el.querySelectorAll("mark.term-mark").length).toBe(1);
  });
});

describe("highlightHtml (pure string → string)", () => {
  it("returns html with marks baked in, matching applyHighlights", () => {
    const html = "<p>The NPA studied irrigated land.</p>";
    const out = highlightHtml(html, ["NPA"], []);
    expect(out).toContain('<mark class="term-mark">NPA</mark>');
    expect(out).toContain("irrigated"); // no false substring match
  });

  it("bakes a cross-tag annotation into the string", () => {
    const out = highlightHtml("<p>were <b>united</b> only</p>", [], [
      { id: 1, quote: "were united only", color: "blue", hasNote: false },
    ]);
    expect(out).toContain('data-annot-ids="1"');
    expect(out).toContain("annot-blue");
  });

  it("returns the input unchanged when nothing matches", () => {
    const html = "<p>nothing to see</p>";
    expect(highlightHtml(html, ["absent"], [])).toBe(html);
  });
});

describe("countTermsPresent", () => {
  it("counts case-insensitively", () => {
    expect(countTermsPresent("The NPA and IRRI", ["npa", "irri", "absent"])).toBe(2);
  });
});
