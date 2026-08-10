/* Screenshot every route at mobile + tablet widths against the running
 * server. Usage: node scripts/mobile-audit.mjs [outdir]  (default shots/) */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = process.env.MANABI_URL ?? "http://localhost:56690";
const OUT = process.argv[2] ?? "shots";

const ROUTES = [
  ["home", "/"],
  ["schedule", "/schedule"],
  ["calendar-month", "/calendar"],
  ["calendar-week", "/calendar?view=week"],
  ["calendar-day", "/calendar?view=day"],
  ["tasks", "/tasks"],
  ["course", "/courses/2"],
  ["module-overview", "/courses/2/modules/2?tab=overview"],
  ["module-materials", "/courses/2/modules/2?tab=materials"],
  ["module-summary", "/courses/2/modules/2?tab=summary"],
  ["module-cards", "/courses/2/modules/2?tab=cards"],
  ["module-quiz", "/courses/2/modules/2?tab=quiz"],
  ["module-chat", "/courses/2/modules/2?tab=chat"],
  ["module-notes", "/courses/2/modules/2?tab=notes"],
  ["viewer", "/documents/7?page=1"],
];

const SIZES = [
  ["m375", { width: 375, height: 812, isMobile: true, hasTouch: true }],
  ["t768", { width: 768, height: 1024, isMobile: true, hasTouch: true }],
];

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
for (const [sizeName, viewport] of SIZES) {
  const ctx = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    isMobile: viewport.isMobile,
    hasTouch: viewport.hasTouch,
    deviceScaleFactor: 2,
  });
  const page = await ctx.newPage();
  for (const [name, route] of ROUTES) {
    try {
      await page.goto(BASE + route, { waitUntil: "networkidle", timeout: 20000 });
      await page.waitForTimeout(600);
      await page.screenshot({
        path: `${OUT}/${name}-${sizeName}.png`,
        fullPage: true,
      });
      console.log(`ok  ${name}-${sizeName}`);
    } catch (e) {
      console.log(`ERR ${name}-${sizeName}: ${e.message.split("\n")[0]}`);
    }
  }
  await ctx.close();
}
await browser.close();
