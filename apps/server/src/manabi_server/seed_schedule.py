"""Seed the 1st-semester 2026–27 courses + weekly schedule blocks.

Idempotent — safe to rerun: matches existing courses by code prefix, never
overwrites an existing accent color, and replaces only the schedule blocks
of seeded courses. Run with:

    uv run --package manabi-server python -m manabi_server.seed_schedule
"""

from manabi_core.models import Course, ScheduleBlock, User
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from manabi_server.config import get_settings

TERM = "1st Sem 2026-27"

# (code, name, instructor, canvas_course_id, [(day 0=Mon, start_min, end_min, room)])
SEED = [
    ("SocSc 14", "POLITICS, GOVERNANCE, AND CITIZENSHIP", "Oliver John C. Quintana",
     70265, [(0, 480, 570, "SEC-B201A"), (3, 480, 570, "SEC-B201A")]),
    ("CSCI 142i", "HUMAN COMPUTER INTERACTION", "Butch Adrian Castro",
     67296, [(0, 570, 660, "CTC 201B"), (3, 570, 660, "CTC 201B")]),
    ("CSCI 70", "STRUCTURE AND INTERPRETATION OF PROGRAMMING LANGUAGES",
     "John Paul C. Vergara",
     67328, [(0, 660, 750, "CTC 506"), (3, 660, 750, "CTC 506")]),
    ("ISCS 30.18", "GUIDED STUDIES IN DATA PREPROCESSING", "Maria Mercedes T. Rodrigo",
     68498, [(3, 780, 840, "F-204")]),
    ("CSCI 161.03", "INTRODUCTION TO SOCIAL COMPUTING", "Juris David Ramos",
     67306, [(0, 840, 930, "F-204"), (3, 840, 930, "F-204")]),
    ("CSCI 60", "COMPUTER NETWORKS AND DATA COMMUNICATIONS", "Stewart Go Roa",
     67302, [(3, 1020, 1200, "CTC 112")]),
    ("CSCI 199.2", "THESIS WRITING II", "John Noel C. Victorino",
     67331, []),  # TBA — no fixed schedule
]

ACCENT_POOL = [
    "#C93A2E", "#28518F", "#3E7A4E", "#B07D1F", "#6A4C93", "#1C2434", "#2E7D8F",
]


def main() -> None:
    engine = create_engine(get_settings().database_url_sync)
    with Session(engine) as db:
        user = db.execute(select(User).order_by(User.id)).scalars().first()
        if user is None:
            raise SystemExit("no user row — start the app once first")

        courses = db.execute(select(Course)).scalars().all()
        used_colors = {c.accent_color for c in courses if c.accent_color}
        free_colors = [c for c in ACCENT_POOL if c not in used_colors]
        max_pos = max((c.position for c in courses), default=-1)

        seeded_ids: list[int] = []
        created = updated = 0
        for code, name, instructor, canvas_id, blocks in SEED:
            course = next(
                (c for c in courses if c.code.lower().startswith(code.lower())), None
            )
            if course is None:
                max_pos += 1
                course = Course(
                    user_id=user.id,
                    code=code,
                    name=name,
                    instructor=instructor,
                    term=TERM,
                    accent_color=free_colors.pop(0) if free_colors else None,
                    position=max_pos,
                    canvas_course_id=canvas_id,
                )
                db.add(course)
                db.flush()
                created += 1
                print(f"created  {code} ({course.accent_color})")
            else:
                course.canvas_course_id = canvas_id
                if not course.instructor:
                    course.instructor = instructor
                if not course.term:
                    course.term = TERM
                updated += 1
                print(f"updated  {course.code} -> canvas {canvas_id}")
            seeded_ids.append(course.id)

            db.execute(delete(ScheduleBlock).where(ScheduleBlock.course_id == course.id))
            for dow, start, end, room in blocks:
                db.add(
                    ScheduleBlock(
                        course_id=course.id,
                        day_of_week=dow,
                        start_minute=start,
                        end_minute=end,
                        location=room,
                    )
                )
        db.commit()

        block_count = db.execute(
            select(func.count()).select_from(ScheduleBlock)
        ).scalar_one()
        print(f"done: {created} created, {updated} updated, {block_count} blocks total")


if __name__ == "__main__":
    main()
