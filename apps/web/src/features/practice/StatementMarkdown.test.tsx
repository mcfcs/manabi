// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { StatementMarkdown } from "./StatementMarkdown";

describe("StatementMarkdown", () => {
  it("typesets set notation instead of showing raw TeX", () => {
    const html = renderToStaticMarkup(
      <StatementMarkdown>{"Strings over $\\{0, 1\\}$ ending in 1."}</StatementMarkdown>
    );
    expect(html).toContain('class="katex"');
    expect(html).not.toContain("$\\{");
  });

  it("leaves dollar-free markdown alone", () => {
    const html = renderToStaticMarkup(<StatementMarkdown>{"Push `x`, then pop."}</StatementMarkdown>);
    expect(html).toContain("<code>x</code>");
  });
});
