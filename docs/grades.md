# Grades & QPI

Manabi tracks grades against the **syllabus'** breakdown, not Canvas's. Canvas
supplies individual assignment scores when a course is linked; the weights, the
letter cutoffs and the arithmetic all live here.

## Why not just read Canvas's grade

Measured against the live Canvas account (Sep 2026):

- `assignment_groups[].group_weight` is `0.0` on every course but one, and
  `apply_assignment_group_weights` is `false` — Canvas does not know the
  syllabus weights.
- `enrollments[].computed_current_score` is `null` everywhere (grades are hidden
  at the course level), so there is no grade to read.
- Some courses (e.g. SocSc 14) have no Canvas assignments at all.

What Canvas *does* give reliably is per-assignment scores, via
`GET /courses/{id}/assignments?include[]=submission` →
`points_possible` and `submission.{score, excused, workflow_state}`.

## The model

A course has:

- **Units** — its weight in the term QPI (Canvas has no such field, so it is
  entered in the course dialog; default 3).
- **Cutoffs** — the lowest percentage that still earns each letter. The ladder
  is always **A / B+ / B / C+ / C / D / F**; only the ranges change, per course,
  from its syllabus. F is implicit: anything below D.
- **Components** — the weighted sections ("Quizzes 30%").
- **Items** — the scores inside a component: either points (`earned / possible`)
  or a straight percentage. A linked Canvas assignment with no score yet is an
  item with `earned = null`.

## How the standing is computed

`apps/server/src/manabi_server/grades.py` (pure, unit-tested):

1. **Item** → a percent. Points divide; a percent row is itself. No score, or a
   Canvas *excused* submission, means "not graded".
2. **Component** → total points across its graded items,
   `Σearned / Σpossible` (a percent row counts as that many points out of 100).
   `null` when nothing in it is graded.
3. **Course** → the weighted average of the components that *have* a grade,
   divided by **their** weight sum, not by 100. So with Participation 10 (95%),
   Quizzes 30 (85%), Paper 40 (88%) and an untouched Project 20, the standing is
   `(95×10 + 85×30 + 88×40) / 80 = 87.75%` — the empty Project never reads as a
   zero.
4. **Letter** → the first cutoff the percent reaches. With A at 93 and B+ at 88,
   92.5 is a B+ and 93 is an A.
5. **QPI** → `Σ(quality points × units) / Σ(units)` over the courses that have a
   letter, on the 4.0 scale: A 4.0, B+ 3.5, B 3.0, C+ 2.5, C 2.0, D 1.0, F 0.
6. **Target line** → what the ungraded weight must average to reach the next
   letter: `(cutoff × total − standing × counted) / remaining`. Above 100 it is
   reported as out of reach.

Nothing is capped at 100, so extra credit counts.

## Canvas linking

"Add from Canvas" on a component lists that course's assignments with their
scores; already-linked ones are disabled. Linking creates items carrying the
Canvas id. **Sync grades** refreshes those rows' score, points and title — it
never adds or removes a row, so re-syncing is idempotent. An assignment can only
be linked once per course; a second attempt is refused with a 409 so nothing is
double counted. An assignment deleted in Canvas leaves its row untouched.

## Where it lives

Grades appear on the **Grades page only** — never on a course page, so opening a
course never puts a mark in front of you. Each row on `/grades` shows a course's
standing and expands into its editor: sections, scores, the scheme and the
Canvas picker. One course is open at a time, and the editor links back to the
course itself.

## Hiding

Settings → Grades → **Hide grades** blurs every percentage, letter and the QPI
wherever they appear (`GradeValue`). The value stays in the DOM so the layout
never shifts; clicking one reveals just that figure for the visit and it hides
itself again on reload.

## API

| Route | Purpose |
|---|---|
| `GET /api/grades` | every course's standing + the term QPI |
| `GET /api/courses/{id}/grades` | one course: components, items, standing, targets |
| `PUT /api/courses/{id}/grades/cutoffs` | save the six cutoffs (validated descending) |
| `POST /api/courses/{id}/grades/components` · `PATCH\|DELETE /api/grades/components/{id}` | sections |
| `POST /api/grades/components/{id}/items` · `PATCH\|DELETE /api/grades/items/{id}` | scores |
| `GET /api/courses/{id}/grades/canvas-assignments` | the picker's feed |
| `POST /api/grades/components/{id}/link` | link Canvas assignments |
| `POST /api/courses/{id}/grades/sync` | refresh linked scores |
| `DELETE /api/courses/{id}/grades` | clear the breakdown (cutoffs kept) |

Tables `grade_components` and `grade_items`, plus `courses.units`,
`courses.grade_cutoffs` and `app_settings.grades_hidden` — migration 0037.
