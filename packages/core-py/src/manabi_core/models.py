"""SQLAlchemy models — Phase 0/1 subset.

Later phases add: documents, document_pages, doc_elements, chunks,
chunk_embeddings, notes, artifacts, flashcards, quiz_*, citations.
Provenance and module isolation live in this module; see docs/plan.
"""

import enum
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 1024


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


class DocumentKind(enum.StrEnum):
    pdf = "pdf"
    pptx = "pptx"


class ExtractStatus(enum.StrEnum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    module_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("modules.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[DocumentKind] = mapped_column(
        Enum(DocumentKind, name="document_kind"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    extract_status: Mapped[ExtractStatus] = mapped_column(
        Enum(ExtractStatus, name="extract_status"),
        nullable=False,
        default=ExtractStatus.pending,
    )
    # Pipeline checkpoint: last completed stage (parse/render/extract/persist/chunk)
    extract_stage: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column()
    # Per-material AI exclusion: enforced in retrieval SQL, not prompts
    ai_included: Mapped[bool] = mapped_column(nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document", order_by="DocumentPage.page_no"
    )

    __table_args__ = (
        UniqueConstraint("module_id", "content_hash", name="uq_documents_module_hash"),
        Index("ix_documents_module_id", "module_id"),
    )


class DocumentPage(Base):
    __tablename__ = "document_pages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_no: Mapped[int] = mapped_column(nullable=False)  # 1-based
    title: Mapped[str | None] = mapped_column(String(512))
    speaker_notes: Mapped[str | None] = mapped_column(Text)
    # Sanitized rich text (<b>/<i>/<p>/<br> only). Native-layer styled text
    # where available; OCR-derived from doc_elements for scanned pages.
    text_html: Mapped[str | None] = mapped_column(Text)
    render_path: Mapped[str | None] = mapped_column(String(1024))
    thumb_path: Mapped[str | None] = mapped_column(String(1024))
    width: Mapped[int | None] = mapped_column()
    height: Mapped[int | None] = mapped_column()

    document: Mapped[Document] = relationship(back_populates="pages")

    __table_args__ = (
        UniqueConstraint("document_id", "page_no", name="uq_document_pages_doc_page"),
    )


class DocElement(Base):
    __tablename__ = "doc_elements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("document_pages.id", ondelete="CASCADE")
    )
    order_index: Mapped[int] = mapped_column(nullable=False)
    element_type: Mapped[str] = mapped_column(String(32), nullable=False)
    text_content: Mapped[str | None] = mapped_column(Text)
    table_json: Mapped[dict | None] = mapped_column(JSONB)
    asset_path: Mapped[str | None] = mapped_column(String(1024))
    bbox: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (Index("ix_doc_elements_document_id", "document_id", "order_index"),)


class Chunk(Base, TimestampMixin):
    """Retrieval unit. module_id is DENORMALIZED on purpose — it is the
    module-isolation key every retrieval query filters on."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    module_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("modules.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_start: Mapped[int] = mapped_column(nullable=False)
    page_end: Mapped[int] = mapped_column(nullable=False)
    element_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    heading_path: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # tsv tsvector GENERATED column + GIN index exist in the DB (migration 0002)
    # but are intentionally not ORM-mapped; retrieval uses SQL directly.

    __table_args__ = (
        Index("ix_chunks_module_id", "module_id"),
        Index("ix_chunks_document_id", "document_id"),
    )


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"

    chunk_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    embedded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ArtifactType(enum.StrEnum):
    summary = "summary"
    flashcard_deck = "flashcard_deck"
    quiz = "quiz"


class Artifact(Base, TimestampMixin):
    """An AI-generated study object. Lineage: artifact → citations →
    chunks → pages → documents → modules → courses."""

    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    module_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("modules.id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[ArtifactType] = mapped_column(
        Enum(ArtifactType, name="artifact_type"), nullable=False
    )
    scope_module_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source_chunk_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    module_version_at_gen: Mapped[int] = mapped_column(nullable=False)
    job_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("jobs.id", ondelete="SET NULL")
    )

    __table_args__ = (Index("ix_artifacts_module_type", "module_id", "artifact_type"),)


class FlashcardStatus(enum.StrEnum):
    active = "active"
    suspended = "suspended"


class Flashcard(Base, TimestampMixin):
    __tablename__ = "flashcards"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    artifact_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False
    )
    ord: Mapped[int] = mapped_column(nullable=False, default=0)
    front: Mapped[str] = mapped_column(Text, nullable=False)
    back: Mapped[str] = mapped_column(Text, nullable=False)
    edited: Mapped[bool] = mapped_column(nullable=False, default=False)
    status: Mapped[FlashcardStatus] = mapped_column(
        Enum(FlashcardStatus, name="flashcard_status"),
        nullable=False,
        default=FlashcardStatus.active,
    )

    __table_args__ = (Index("ix_flashcards_artifact_id", "artifact_id"),)


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    artifact_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False
    )
    ord: Mapped[int] = mapped_column(nullable=False, default=0)
    qtype: Mapped[str] = mapped_column(String(16), nullable=False)  # mcq|tf|short
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list | None] = mapped_column(JSONB)  # mcq choices
    answer: Mapped[dict] = mapped_column(JSONB, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_quiz_questions_artifact_id", "artifact_id"),)


class QuizAttempt(Base, TimestampMixin):
    __tablename__ = "quiz_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    artifact_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responses: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    score: Mapped[float | None] = mapped_column()

    __table_args__ = (Index("ix_quiz_attempts_artifact_id", "artifact_id"),)


class CitationStatus(enum.StrEnum):
    verified = "verified"
    weak = "weak"
    source_removed = "source_removed"


class Citation(Base):
    """Provenance edge from an artifact item to a chunk. Denormalized doc
    title/pages keep the label renderable after the chunk is deleted."""

    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    artifact_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False
    )
    item_ref: Mapped[str] = mapped_column(String(64), nullable=False)  # 'sec:0:block:2'
    chunk_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("chunks.id", ondelete="SET NULL")
    )
    # Elements within the chunk that actually support this claim (precise
    # highlight targets); NULL = fall back to all chunk elements
    element_ids: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger))
    document_id: Mapped[int | None] = mapped_column(BigInteger)
    document_title: Mapped[str] = mapped_column(String(512), nullable=False)
    page_start: Mapped[int | None] = mapped_column()
    page_end: Mapped[int | None] = mapped_column()
    quote_excerpt: Mapped[str | None] = mapped_column(Text)
    support_score: Mapped[float | None] = mapped_column()
    status: Mapped[CitationStatus] = mapped_column(
        Enum(CitationStatus, name="citation_status"),
        nullable=False,
        default=CitationStatus.verified,
    )

    __table_args__ = (
        Index("ix_citations_artifact_id", "artifact_id"),
        Index("ix_citations_chunk_id", "chunk_id"),
    )


class Note(Base, TimestampMixin):
    """User-authored — never cascaded by any document/AI operation."""

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    module_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("modules.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    pm_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    plain_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class NoteSnapshot(Base, TimestampMixin):
    __tablename__ = "note_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    note_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("notes.id", ondelete="CASCADE"), nullable=False
    )
    pm_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class Annotation(Base, TimestampMixin):
    """User highlight (+ optional note) on a document's extracted text.
    Anchored by exact quote + page number — resilient to re-renders; if the
    text is later re-extracted and the quote no longer matches, the
    annotation surfaces as 'unanchored' instead of being lost."""

    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_no: Mapped[int] = mapped_column(nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str] = mapped_column(String(16), nullable=False, default="yellow")

    __table_args__ = (Index("ix_annotations_document_id", "document_id"),)


class ChatThread(Base, TimestampMixin):
    """Per-module chat conversations; history persists with the module."""

    __tablename__ = "chat_threads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    module_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("modules.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (Index("ix_chat_threads_module_id", "module_id"),)


class ChatRole(enum.StrEnum):
    user = "user"
    assistant = "assistant"


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chat_threads.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[ChatRole] = mapped_column(Enum(ChatRole, name="chat_role"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # grounded=True: answered from module materials (citations present).
    # general_knowledge=True: sources didn't cover it; model knowledge used,
    # clearly labeled in the UI.
    grounded: Mapped[bool] = mapped_column(nullable=False, default=True)
    general_knowledge: Mapped[bool] = mapped_column(nullable=False, default=False)
    citations: Mapped[list | None] = mapped_column(JSONB)  # snapshot list
    job_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("jobs.id", ondelete="SET NULL")
    )

    __table_args__ = (Index("ix_chat_messages_thread_id", "thread_id"),)


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
    # Rolling tail of the model's streamed output while generating
    preview: Mapped[str | None] = mapped_column(Text)
    procrastinate_job_id: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)
    module_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("modules.id", ondelete="SET NULL")
    )
    document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="SET NULL")
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
