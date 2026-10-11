import { describe, expect, it } from "vitest";

import { activeToken, locate, tokenStarts, wordFor, wordRanges } from "./narrationHighlight";

function page(html: string): HTMLElement {
  const el = document.createElement("div");
  el.innerHTML = html;
  return el;
}

describe("narration highlight", () => {
  it("finds a paragraph in the page text across markup and punctuation", () => {
    const el = page(
      "<p>Intro text here.</p><p><b>Under</b> martial law, Marcos clamped down on all dissent.</p>",
    );
    const words = wordRanges(el);
    const tokens = "Under martial law, Marcos clamped down on all dissent.".split(" ");
    const start = locate(words, tokens);
    expect(start).toBe(3);
    expect(wordFor(words, start, tokens, 3)?.range.toString()).toBe("Marcos");
  });

  it("tolerates one OCR difference in the opening words", () => {
    const words = wordRanges(page("<p>Marcos alsò had to contend with armed resistance</p>"));
    const tokens = "Marcos also had to contend with armed resistance".split(" ");
    expect(locate(words, tokens)).toBe(0);
  });

  it("returns -1 when the paragraph is on another page", () => {
    const words = wordRanges(page("<p>Something else entirely is written here today.</p>"));
    expect(locate(words, "Under martial law Marcos clamped down".split(" "))).toBe(-1);
  });

  it("uses recorded timings, or spreads the words by length before alignment", () => {
    expect(tokenStarts(["a", "b"], [0, 500], 1000)).toEqual([0, 500]);
    const est = tokenStarts(["one", "three"], null, 800);
    expect(est[0]).toBe(0);
    expect(est[1]).toBe(300); // 3 of 8 characters in
  });

  it("picks the word being spoken", () => {
    const starts = [0, 400, 900, 1500];
    expect(activeToken(starts, 0)).toBe(0);
    expect(activeToken(starts, 899)).toBe(1);
    expect(activeToken(starts, 5000)).toBe(3);
  });
});
