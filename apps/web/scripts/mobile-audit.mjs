/* Screenshot every route at the app's breakpoint tiers against the ALREADY
 * RUNNING server (never start servers from here), and print a layout table:
 * rail width, horizontal overflow, and the content-column width per page.
 *
 * Usage:  node scripts/mobile-audit.mjs [outdir]           (default shots/)
 * Env:    MANABI_URL (default http://localhost:56690)
 *         MANABI_COURSE / MANABI_MODULE / MANABI_DOC  — ids for the deep routes
 *         SIZES=390,1024  — subset of the widths below
 *         ONLY=module-,viewer — only routes whose name contains one of these
 */
import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const BASE = process.env.MANABI_URL ?? "http://localhost:56690";
const OUT = process.argv[2] ?? "shots";
const COURSE = process.env.MANABI_COURSE ?? "2";
const MODULE = process.env.MANABI_MODULE ?? "2";
const DOC = process.env.MANABI_DOC ?? "7";

const ROUTES = [
  ["home", "/"],
  ["assistant", "/assistant"],
  ["schedule", "/schedule"],
  ["calendar-month", "/calendar"],
  ["calendar-week", "/calendar?view=week"],
  ["calendar-day", "/calendar?view=day"],
  ["tasks", "/tasks"],
  ["review", "/review"],
  ["course", `/courses/${COURSE}`],
  ["module-overview", `/courses/${COURSE}/modules/${MODULE}?tab=overview`],
  ["module-materials", `/courses/${COURSE}/modules/${MODULE}?tab=materials`],
  ["module-summary", `/courses/${COURSE}/modules/${MODULE}?tab=summary`],
  ["module-cards", `/courses/${COURSE}/modules/${MODULE}?tab=cards`],
  ["module-quiz", `/courses/${COURSE}/modules/${MODULE}?tab=quiz`],
  ["module-chat", `/courses/${COURSE}/modules/${MODULE}?tab=chat`],
  ["module-notes", `/courses/${COURSE}/modules/${MODULE}?tab=notes`],
  ["viewer", `/documents/${DOC}?page=1`],
];

// width → [height, touch]. Phone, iPad portrait (768 + Air 834), iPad
// landscape (1024 + Pro-11 1194), desktop.
const ALL_SIZES = {
  390: [844, true],
  768: [1024, true],
  834: [1194, true],
  1024: [768, true],
  1194: [834, true],
  1440: [900, false],
};
const only = (process.env.ONLY ?? "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);
const routes = only.length ? ROUTES.filter(([n]) => only.some((o) => n.includes(o))) : ROUTES;
const widths = (process.env.SIZES ?? Object.keys(ALL_SIZES).join(","))
  .split(",")
  .map((w) => Number(w.trim()))
  .filter((w) => w in ALL_SIZES);

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
const rows = [];
for (const width of widths) {
  const [height, touch] = ALL_SIZES[width];
  const ctx = await browser.newContext({
    viewport: { width, height },
    isMobile: touch && width < 1024,
    hasTouch: touch,
    deviceScaleFactor: 2,
  });
  const page = await ctx.newPage();
  for (const [name, route] of routes) {
    try {
      await page.goto(BASE + route, { waitUntil: "networkidle", timeout: 20000 });
      await page.waitForTimeout(700);
      const m = await page.evaluate(() => {
        const rail = document.querySelector(".rail");
        const content = document.querySelector(".content");
        const railW = rail && getComputedStyle(rail).display !== "none" ? rail.getBoundingClientRect().width : 0;
        const cs = content ? getComputedStyle(content) : null;
        const contentInner = content
          ? content.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)
          : 0;
        const overflow = document.documentElement.scrollWidth - window.innerWidth;
        // widest descendant that pokes past the content box (first offender)
        let offender = null;
        if (content) {
          const right = content.getBoundingClientRect().right;
          for (const el of content.querySelectorAll("*")) {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.right > right + 1) {
              offender = `${el.tagName.toLowerCase()}.${String(el.className).split(" ")[0]} +${Math.round(r.right - right)}px`;
              break;
            }
          }
        }
        return { railW: Math.round(railW), contentInner: Math.round(contentInner), overflow, offender };
      });
      rows.push({ width, name, ...m });
      await page.screenshot({ path: `${OUT}/${name}-w${width}.png`, fullPage: true });
      console.log(
        `ok  ${String(width).padEnd(5)} ${name.padEnd(17)} rail=${String(m.railW).padStart(3)} ` +
          `content=${String(m.contentInner).padStart(4)} overflow=${String(m.overflow).padStart(3)}` +
          (m.offender ? `  ! ${m.offender}` : ""),
      );
    } catch (e) {
      rows.push({ width, name, error: e.message.split("\n")[0] });
      console.log(`ERR ${width} ${name}: ${e.message.split("\n")[0]}`);
    }
  }
  await ctx.close();
}
await browser.close();
writeFileSync(`${OUT}/metrics.json`, JSON.stringify(rows, null, 2));
console.log(`\nwrote ${rows.length} rows to ${OUT}/metrics.json`);
