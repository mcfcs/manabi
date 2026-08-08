"""SQLAlchemy models — Phase 0/1 subset.

Later phases add: documents, document_pages, doc_elements, chunks,
chunk_embeddings, notes, artifacts, flashcards, quiz_*, citations.
Provenance and module isolation live in this module; see docs/plan.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSON}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"

    # sha256 of the random session token; the raw token exists only in the cookie
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_sessions_expires_at", "expires_at"),)


class Course(Base, TimestampMixin):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    instructor: Mapped[str | None] = mapped_column(String(255))
    term: Mapped[str | None] = mapped_column(String(64))
    accent_color: Mapped[str | None] = mapped_column(String(16))
    position: Mapped[int] = mapped_column(nullable=False, default=0)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    modules: Mapped[list["Module"]] = relationship(
        back_populates="course", order_by="Module.position"
    )

    __table_args__ = (Index("ix_courses_user_id", "user_id"),)


class Module(Base, TimestampMixin):
    __tablename__ = "modules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    course_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(nullable=False, default=0)
    # Staleness trigger: bumped on document add/remove/re-extract and note edits
    content_version: Mapped[int] = mapped_column(nullable=False, default=0)

    course: Mapped[Course] = relationship(back_populates="modules")

    __table_args__ = (Index("ix_modules_course_id", "course_id"),)


class JobQueue(enum.StrEnum):
    cpu = "cpu"
    gpu = "gpu"


class JobStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class Job(Base, TimestampMixin):
    """App-facing job record; Procrastinate's own tables stay internal."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    queue: Mapped[JobQueue] = mapped_column(Enum(JobQueue, name="job_queue"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), nullable=False, default=JobStatus.queued
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON)
    progress_pct: Mapped[int | None] = mapped_column()
    progress_note: Mapped[str | None] = mapped_column(String(255))
    procrastinate_job_id: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)
    module_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("modules.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_jobs_status_created_at", "status", "created_at"),
        Index("ix_jobs_module_id", "module_id"),
    )


class AINodeHeartbeat(Base):
    """Freshness of this row is the 'AI ● online' signal — no health-probe protocol."""

    __tablename__ = "ai_node_heartbeats"

    worker_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    gpu_info: Mapped[dict | None] = mapped_column(JSON)
