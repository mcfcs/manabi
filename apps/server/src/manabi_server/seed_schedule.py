"""Seed courses + weekly schedule blocks from a local JSON file.

Idempotent — safe to rerun: matches existing courses by code prefix, never
overwrites an existing accent color, and replaces only the schedule blocks
of seeded courses.

The data (course codes, instructors, rooms, Canvas ids) is personal and lives
OUTSIDE version control: ``apps/server/seed_schedule.local.json`` (gitignored),
or any path in ``MANABI_SEED_FILE``. Start from ``seed_schedule.example.json``.

    uv run --package manabi-server python -m manabi_server.seed_schedule
    uv run --package manabi-server python -m manabi_server.seed_schedule --example
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from manabi_core.models import Course, Schedule, ScheduleBlock, User
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from manabi_server.config import get_settings

SERVER_DIR = Path(__file__).resolve().parents[2]  # apps/server
LOCAL_SEED = SERVER_DIR / "seed_schedule.local.json"
EXAMPLE_SEED = SERVER_DIR / "seed_schedule.example.json"

ACCENT_POOL = [
    "#C93A2E",
    "#28518F",
    "#3E7A4E",
    "#B07D1F",
    "#6A4C93",
    "#1C2434",
    "#2E7D8F",
]


@dataclass(frozen=True)
class SeedBlock:
    day: int  # 0 = Monday … 6 = Sunday
    start: int  # minutes from midnight
    end: int
    room: str | None = None


@dataclass(frozen=True)
class SeedCourse:
    code: str
    name: str
    instructor: str | None
    canvas_course_id: int | None
    blocks: tuple[SeedBlock, ...]  # empty = TBA (still shown on the schedule)


@dataclass(frozen=True)
class Seed:
    term: str
    courses: tuple[SeedCourse, ...]
    source: Path


def seed_path(*, allow_example: bool = False) -> Path:
    """Resolve the data file: env override, then the local file, then (only
    when explicitly allowed) the tracked example."""
    override = os.environ.get("MANABI_SEED_FILE")
    if override:
        return Path(override)
    if LOCAL_SEED.is_file():
        return LOCAL_SEED
    if allow_example:
        return EXAMPLE_SEED
    raise SystemExit(
        f"no seed data: copy {EXAMPLE_SEED.name} to {LOCAL_SEED} and fill it in, "
        "set MANABI_SEED_FILE, or pass --example to seed the fictional sample."
    )


def _block(raw: dict) -> SeedBlock:
    block = SeedBlock(
        day=int(raw["day"]),
        start=int(raw["start"]),
        end=int(raw["end"]),
        room=raw.get("room") or None,
    )
    if not 0 <= block.day <= 6:
        raise ValueError(f"block day must be 0..6, got {block.day}")
    if not 0 <= block.start < block.end <= 24 * 60:
        raise ValueError(f"block minutes out of order: {block.start}-{block.end}")
    return block


def load_seed(path: Path | None = None) -> Seed:
    path = path or seed_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    term = str(data["term"]).strip()
    if not term:
        raise ValueError("seed term is empty")
    courses = tuple(
        SeedCourse(
            code=str(c["code"]).strip(),
            name=str(c["name"]).strip(),
            instructor=(c.get("instructor") or None),
            canvas_course_id=(
                int(c["canvas_course_id"]) if c.get("canvas_course_id") is not None else None
            ),
            blocks=tuple(_block(b) for b in c.get("blocks", [])),
        )
        for c in data["courses"]
    )
    if not courses:
        raise ValueError("seed has no courses")
    return Seed(term=term, courses=courses, source=path)


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    seed = load_seed(seed_path(allow_example="--example" in args))
    print(f"seeding from {seed.source}")

    engine = create_engine(get_settings().database_url_sync)
    with Session(engine) as db:
        user = db.execute(select(User).order_by(User.id)).scalars().first()
        if user is None:
            raise SystemExit("no user row — start the app once first")

        class_sched = (
            db.execute(select(Schedule).where(Schedule.title == "Class schedule")).scalars().first()
        )
        if class_sched is None:
            class_sched = Schedule(title="Class schedule", position=0)
            db.add(class_sched)
            db.flush()

        internship = (
            db.execute(select(Schedule).where(Schedule.title == "Internship")).scalars().first()
        )
        if internship is None:
            internship = Schedule(title="Internship", position=1)
            db.add(internship)
            db.flush()
            db.add(ScheduleBlock(schedule_id=internship.id, label="Internship", color="#2E7D8F"))
            print("created  Internship schedule (TBA)")

        courses = db.execute(select(Course)).scalars().all()
        used_colors = {c.accent_color for c in courses if c.accent_color}
        free_colors = [c for c in ACCENT_POOL if c not in used_colors]
        max_pos = max((c.position for c in courses), default=-1)

        seeded_ids: list[int] = []
        created = updated = 0
        for entry in seed.courses:
            course = next(
                (c for c in courses if c.code.lower().startswith(entry.code.lower())),
                None,
            )
            if course is None:
                max_pos += 1
                course = Course(
                    user_id=user.id,
                    code=entry.code,
                    name=entry.name,
                    instructor=entry.instructor,
                    term=seed.term,
                    accent_color=free_colors.pop(0) if free_colors else None,
                    position=max_pos,
                    canvas_course_id=entry.canvas_course_id,
                )
                db.add(course)
                db.flush()
                created += 1
                print(f"created  {entry.code} ({course.accent_color})")
            else:
                course.canvas_course_id = entry.canvas_course_id
                if not course.instructor:
                    course.instructor = entry.instructor
                if not course.term:
                    course.term = seed.term
                updated += 1
                print(f"updated  {course.code} -> canvas {entry.canvas_course_id}")
            seeded_ids.append(course.id)

            db.execute(delete(ScheduleBlock).where(ScheduleBlock.course_id == course.id))
            if not entry.blocks:  # TBA course — still shows on the schedule
                db.add(ScheduleBlock(schedule_id=class_sched.id, course_id=course.id))
            for block in entry.blocks:
                db.add(
                    ScheduleBlock(
                        schedule_id=class_sched.id,
                        course_id=course.id,
                        day_of_week=block.day,
                        start_minute=block.start,
                        end_minute=block.end,
                        location=block.room,
                    )
                )
        db.commit()

        block_count = db.execute(select(func.count()).select_from(ScheduleBlock)).scalar_one()
        print(f"done: {created} created, {updated} updated, {block_count} blocks total")


if __name__ == "__main__":
    main()
