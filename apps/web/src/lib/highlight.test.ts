import { describe, expect, it } from "vitest";

import { highlightAnnotations, highlightTerms } from "./highlight";

describe("highlightTerms", () => {
  it("wraps matches only in text segments, never inside tags", () => {
    const html = '<p class="attenuation">Signal attenuation grows.</p>';
    const out = highlightTerms(html, ["attenuation"]);
    expect(out).toContain('class="attenuation"'); // attribute untouched
    expect(out).toContain('<mark class="term-mark">attenuation</mark> grows');
  });
});

describe("highlightAnnotations", () => {
  const annot = { id: 7, quote: "time-division multiplexing", color: "yellow", hasNote: true };

  it("wraps the quote in a clickable mark with id and color", () => {
    const out = highlightAnnotations("<p>Uses time-division multiplexing here.</p>", [annot]);
    expect(out).toContain('data-annot="7"');
    expect(out).toContain("annot-yellow");
    expect(out).toContain("has-note");
    expect(out).toContain(">time-division multiplexing</mark>");
  });

  it("marks only the first occurrence", () => {
    const out = highlightAnnotations("<p>DS-1 and DS-1 again</p>", [
      { id: 1, quote: "DS-1", color: "blue", hasNote: false },
    ]);
    expect(out.match(/<mark/g)).toHaveLength(1);
  });

  it("never rewrites tag internals even when the quote appears in an attribute", () => {
    const html = '<p style="margin-left:1em">margin-left is an indent</p>';
    const out = highlightAnnotations(html, [
      { id: 2, quote: "margin-left", color: "green", hasNote: false },
    ]);
    expect(out).toContain('style="margin-left:1em"');
    expect(out).toContain(">margin-left</mark> is an indent");
  });

  it("escapes regex metacharacters in quotes", () => {
    const out = highlightAnnotations("<p>cost is $1.50 (approx)</p>", [
      { id: 3, quote: "$1.50 (approx)", color: "red", hasNote: false },
    ]);
    expect(out).toContain(">$1.50 (approx)</mark>");
  });

  it("leaves html unchanged when the quote no longer matches", () => {
    const html = "<p>The text was edited.</p>";
    const out = highlightAnnotations(html, [
      { id: 4, quote: "vanished sentence", color: "yellow", hasNote: false },
    ]);
    expect(out).toBe(html);
  });
});
