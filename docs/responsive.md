# Responsive layout — scale, rail, rules

Manabi targets four widths: iPhone, iPad portrait, iPad landscape, desktop.
Everything below is enforced by plain CSS in `apps/web/src`; there is no
Tailwind and no JS breakpoint hook.

## Breakpoint scale

Media queries cannot read custom properties, so these values are literals.
Use exactly these; do not invent 760 / 820 / 1080-style one-offs.

| Tier | Query | Rail | Content inset | Feature sidebars |
|---|---|---|---|---|
| Phone | `max-width: 767px` | hidden, bottom nav | 16px + 64px nav clearance | stacked / drawers |
| Tablet portrait | `768px–1023px` | compact 72px icon rail | 24px | collapsed (chip strips, drawers) |
| Tablet landscape | `1024px–1279px` | compact 72px icon rail | 24px | open |
| Desktop | `min-width: 1280px` | full 216px rail | 32px | open |

Resulting content column (viewport − rail − 2 × inset):

| Viewport | 390 | 768 | 834 | 1024 | 1194 | 1440 |
|---|---|---|---|---|---|---|
| Content px | 358 | 648 | 714 | 904 | 1074 | 1160 |

Rule of thumb: a secondary column (thread list, jump-nav, sections sidebar)
needs ≥ ~900px of content, so it appears from 1024 up. Anything narrower
collapses it into a strip above the main column or a drawer.

## Tokens (`styles/tokens.css`, overridden per tier in `app/shell.css` on `:root`)

- `--rail-width` — 216px / 72px. The rail reads it; nothing else should.
- `--content-pad` — the `.content` inset (32 / 24 / 16).
- `--content-pad-bottom` — bottom inset; on phones = `--bottom-nav-h` + safe area.
- `--bottom-nav-h` — 0 / 64px.

Pinned (fixed-height) layouts — module chat, the assistant, the document
viewer — size themselves with

```css
height: calc(100dvh - var(--content-pad) - var(--content-pad-bottom));
```

and never hard-code the padding or the nav. The tokens live on `:root`
(not `.shell`) so panels portalled to `<body>` inherit them.

## The compact rail (768–1279)

`shell.css` turns `.rail-link` into icon-over-label columns, hides text
that has no room (`.rail-name`, headings, recents, the user email, the ⌘K
kbd) and turns section headings into hairline dividers. Course links show
the accent dot plus `shortCourseCode()` (the code's trailing token) with the
full code and name as a tooltip. Due badges pin to the icon.

## Three rules that keep biting

1. **Flex children need `min-width: 0` / `min-height: 0`** to shrink below
   their content; otherwise a long title blows a sidebar out to its
   min-content width (`assistant.css` documents the 550px case).
2. **Portal `position: fixed` overlays to `document.body`.** `.content > *`
   animates route entry with a `transform`, which makes the route element
   the containing block for fixed descendants. `components/Modal`,
   `calendar/DayPanel`, the chat drawer/sheets and the viewer's annotation
   panels are all portalled for this reason. `.notes-drawer` and
   `.viewer-discuss` are intentionally `absolute` to `.viewer`.
3. **Never paint a permanent mask above a sticky bar.** Gate it on an
   `is-stuck` class driven by an IntersectionObserver sentinel (see the
   notes toolbar).

JS-side `matchMedia("(max-width: 767px)")` in `ChatComposer` (Enter sends vs
newlines), `DocumentViewer.useIsMobile` (iframe vs image fallback) and
`FloatingPanels` (bottom sheet) are about touch/phone semantics, not layout
width, and deliberately stay at 767.

## Per-feature behaviour

| Feature | Phone | Tablet portrait | Tablet landscape+ |
|---|---|---|---|
| Module tab bar | scroll + fade + snap | scroll + fade + snap | fits |
| Chat / Steven | drawer + settings sheet, pinned composer | drawer + sheet | 220px thread sidebar, inline toggles |
| Summary | jump-nav chip strip | chip strip | sticky 190px jump-nav |
| Notes | sections strip | sections strip | 190px sections sidebar |
| Flashcards / quiz | rows wrap; player ≤ 640px | rows wrap | full |
| Schedule | stacked day list | 5-column grid, no instructor line | full grid |
| Calendar | compact chips; week scrolls sideways; day panel = bottom sheet | compact chips; week scrolls if needed; day panel = right drawer | full |
| Viewer | stacked page + text | stacked | two-column reading |
| Course page | header actions on their own row | same | inline |
| Home | 1–2 course cards per row | 2 | 3–4 |

## Verifying

Against the already-running app (start it with `start-manabi.bat`):

```
cd apps/web
MANABI_COURSE=2 MANABI_MODULE=2 MANABI_DOC=3 node scripts/mobile-audit.mjs shots
ONLY=module-,viewer SIZES=768,1024 node scripts/mobile-audit.mjs shots   # subset
```

It screenshots every route at 390 / 768 / 834 / 1024 / 1194 / 1440 and
prints, per page, the rail width, the content column width, any horizontal
page overflow, and the first element poking past the content box. `shots/`
is gitignored — delete it when done.
