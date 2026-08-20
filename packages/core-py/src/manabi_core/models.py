"""SQLAlchemy models — Phase 0/1 subset.

Later phases add: documents, document_pages, doc_elements, chunks,
chunk_embeddings, notes, artifacts, flashcards, quiz_*, citations.
Provenance and module isolation live in this module; see docs/plan.
"""

import enum
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
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
    canvas_course_id: Mapped[int | None] = mapped_column(BigInteger)
    meeting_url: Mapped[str | None] = mapped_column(String(512))  # gmeet/zoom
    cover_image_path: Mapped[str | None] = mapped_column(String(1024))  # cosmetic card cover

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
    # Hidden "Course files" container (syllabus, COA, …) — excluded from
    # module lists; its documents default to no extraction / no AI.
    is_general: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Source Canvas module id when this module was cloned from Canvas — dedup key
    # so re-syncing updates in place instead of duplicating.
    canvas_module_id: Mapped[int | None] = mapped_column(BigInteger)

    course: Mapped[Course] = relationship(back_populates="modules")

    __table_args__ = (
        Index("ix_modules_course_id", "course_id"),
        Index("ix_modules_canvas_module_id", "canvas_module_id"),
    )


class CourseLink(Base, TimestampMixin):
    """An external resource link (Canvas ExternalUrl module-item, or a manually
    added URL). Links can't be AI-chunked — they're an openable reference list
    on the course / module."""

    __tablename__ = "course_links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    course_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    module_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("modules.id", ondelete="CASCADE")
    )
    # Canvas module-item id — dedup key so re-sync upserts instead of duplicating.
    canvas_item_id: Mapped[int | None] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    position: Mapped[int] = mapped_column(nullable=False, default=0)

    __table_args__ = (
        Index("ix_course_links_course_id", "course_id"),
        Index(
            "uq_course_links_canvas_item",
            "course_id",
            "canvas_item_id",
            unique=True,
            postgresql_where=text("canvas_item_id IS NOT NULL"),
        ),
    )


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
    # 'full' or 'render_only' (store + view pages, skip text extraction/AI)
    processing_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="full"
    )
    # Two-page-spread handling: 'auto' (detect) | 'single' | 'spread' (force split).
    page_layout: Mapped[str] = mapped_column(String(8), nullable=False, default="auto")
    # What auto-detection concluded on the last extract: 'single' | 'spread' | None.
    detected_layout: Mapped[str | None] = mapped_column(String(8))
    # Origin URL when ingested from external content (a Canvas Page / discussion
    # / syllabus rendered to PDF) — lets re-sync update in place.
    source_url: Mapped[str | None] = mapped_column(String(1024))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document", order_by="DocumentPage.page_no"
    )

    __table_args__ = (
        # Partial unique: a soft-deleted document must not block re-uploading
        # the same file (the dedup query also filters deleted_at IS NULL).
        Index(
            "uq_documents_module_hash",
            "module_id",
            "content_hash",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
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
    lecture = "lecture"


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
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="Notes")
    position: Mapped[int] = mapped_column(nullable=False, default=0)
    pm_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    plain_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_notes_module_id", "module_id"),)


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


class SummaryHighlight(Base, TimestampMixin):
    """User highlight (+ optional note) on a summary artifact's prose. Anchored
    by exact quote (re-found in the rendered blocks) — the summary analogue of
    Annotation, which is document/page-anchored and so can't cover an artifact."""

    __tablename__ = "summary_highlights"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    artifact_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False
    )
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str] = mapped_column(String(16), nullable=False, default="yellow")

    __table_args__ = (Index("ix_summary_highlights_artifact_id", "artifact_id"),)


class ChatThread(Base, TimestampMixin):
    """Chat conversations. Per-module (module_id set) OR general/personal
    (module_id NULL — the "Manabi AI" assistant). Ownership is by user_id so
    both kinds share one ownership check."""

    __tablename__ = "chat_threads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Owner — set on both module and general threads (general threads have no
    # module to derive it from).
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # NULL = a general/assistant thread (not tied to a module).
    module_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("modules.id", ondelete="CASCADE")
    )
    # Teacher persona (Steven) — changes voice, never grounding
    teacher_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Material scope: NULL = all module materials, [] = none of that kind.
    scope_document_ids: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger))
    scope_note_ids: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger))
    # General-assistant cross-module material scope: NULL/[] = none forced.
    scope_module_ids: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger))
    # General assistant: auto-scan the user's materials when the question is
    # relevant (cosine-gated), instead of never scanning by default.
    auto_materials: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # General assistant: per-chat model override (NULL = use the global
    # general_chat_model, else the node's effective_chat_model). Never applied to
    # module threads.
    model_override: Mapped[str | None] = mapped_column(String(128))
    # True = strict material-first grounding; False = material + free reasoning.
    strict_grounding: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Viewer-originated "discussion": the passage/page this thread is about.
    source_document_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="SET NULL")
    )
    source_page: Mapped[int | None] = mapped_column()
    # Multi-page "Ask about pages 1-3, 5": the exact pages that ground this
    # thread. NULL = single-page/passage (use source_page/source_quote).
    source_pages: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger))
    source_quote: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_chat_threads_module_id", "module_id"),
        Index("ix_chat_threads_user_id", "user_id"),
    )


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
    # An assistant-proposed action (Steven "takes actions"): {kind, status,
    # summary, params, result?}. NULL = a normal message. Nothing executes until
    # the user confirms — the server re-reads this to run it.
    action: Mapped[dict | None] = mapped_column(JSONB)
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


# ── Increment 9: schedule, calendar, tasks, push ──────────────────────────
# Timezone rule: calendar-shaped data stores naive local (Asia/Manila) values
# as DATE + minutes-since-midnight INT columns. Audit fields (done_at, …)
# stay timestamptz. Conversions happen only at boundaries (Canvas, Google).


class Schedule(Base, TimestampMixin):
    """Named schedule group (Class schedule, Internship, ...)."""

    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    position: Mapped[int] = mapped_column(nullable=False, default=0)


class ScheduleBlock(Base, TimestampMixin):
    """One entry of a schedule: course-linked or free-label, timed or TBA
    (day_of_week/start/end NULL)."""

    __tablename__ = "schedule_blocks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    schedule_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("courses.id", ondelete="CASCADE")
    )
    label: Mapped[str | None] = mapped_column(String(128))  # used when no course
    color: Mapped[str | None] = mapped_column(String(16))
    day_of_week: Mapped[int | None] = mapped_column(SmallInteger)  # 0=Mon, NULL=TBA
    start_minute: Mapped[int | None] = mapped_column()
    end_minute: Mapped[int | None] = mapped_column()
    location: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_schedule_blocks_course_id", "course_id"),
        CheckConstraint(
            "start_minute IS NULL OR end_minute IS NULL OR end_minute > start_minute",
            name="ck_schedule_block_range",
        ),
    )


class AppSettings(Base):
    """Single-row app configuration (id always 1)."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    semester_start: Mapped[date] = mapped_column(Date, nullable=False)
    semester_end: Mapped[date] = mapped_column(Date, nullable=False)
    gcal_ics_url: Mapped[str | None] = mapped_column(Text)
    gcal_last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gcal_last_error: Mapped[str | None] = mapped_column(Text)
    class_reminders: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_announcement_id: Mapped[int | None] = mapped_column(BigInteger)
    canvas_last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canvas_last_error: Mapped[str | None] = mapped_column(Text)
    # Auto-play Steven's voice for chat replies (default off; per-device toggle
    # in the chat UI overrides this for the session).
    chat_autovoice: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Ollama model for the general "Manabi AI" assistant. NULL = fall back to the
    # worker's effective_chat_model. Does NOT affect per-module chat.
    general_chat_model: Mapped[str | None] = mapped_column(String(128))
    # Manila date of the most recent daily briefing produced (Steven's "good day"
    # digest). NULL = never. Gates once-per-day generation on assistant open.
    last_briefing_date: Mapped[date | None] = mapped_column(Date)


class CalendarEvent(Base, TimestampMixin):
    """User-created event: one-off or weekly-repeating until a date."""

    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    course_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("courses.id", ondelete="SET NULL")
    )
    # Categorize under a schedule group (e.g. Internship) instead of a course —
    # the event then takes that schedule's color and filter.
    schedule_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("schedules.id", ondelete="SET NULL")
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    start_minute: Mapped[int | None] = mapped_column()  # both NULL = all-day
    end_minute: Mapped[int | None] = mapped_column()
    repeat_weekly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    repeat_until: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (Index("ix_calendar_events_date", "date"),)


class DayMark(Base):
    """Per-date location declaration. For classes: whole day (course_id NULL) or
    one course, mode sync|async. For a labeled schedule block (block_id set,
    e.g. an internship): mode rto|wfh."""

    __tablename__ = "day_marks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    course_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("courses.id", ondelete="CASCADE")
    )
    # Set instead of course_id when the mark targets a non-course schedule block
    # (internship / org duty) — its RTO/WFH state for that date.
    block_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("schedule_blocks.id", ondelete="CASCADE")
    )
    mode: Mapped[str] = mapped_column(String(8), nullable=False)  # sync|async|rto|wfh
    note: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (
        UniqueConstraint(
            "date", "course_id", "block_id", name="uq_day_marks_date_course",
            postgresql_nulls_not_distinct=True,
        ),
    )


class GcalEvent(Base):
    """Read-only cache of the user's Google Calendar (secret ICS feed).
    Wiped and rewritten on every fetch — never edited locally."""

    __tablename__ = "gcal_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    uid: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    calendar: Mapped[str | None] = mapped_column(String(128))  # source feed name
    date: Mapped[date] = mapped_column(Date, nullable=False)
    start_minute: Mapped[int | None] = mapped_column()  # NULL = all-day
    end_minute: Mapped[int | None] = mapped_column()
    location: Mapped[str | None] = mapped_column(String(255))
    organizer: Mapped[str | None] = mapped_column(String(255))
    # [{name, status}] — status: accepted | declined | tentative | needs-action
    attendees: Mapped[list | None] = mapped_column(JSONB)
    # This user's PARTSTAT (matched by the feed-owner email in the ICS URL)
    my_status: Mapped[str | None] = mapped_column(String(16))

    __table_args__ = (Index("ix_gcal_events_date", "date"),)


class StudyTask(Base, TimestampMixin):
    """User task, optionally imported from a Canvas assignment."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    course_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("courses.id", ondelete="SET NULL")
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    due_minute: Mapped[int | None] = mapped_column()
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    canvas_assignment_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_tasks_due_date", "due_date"),)


class PushSubscription(Base, TimestampMixin):
    """Web Push subscription (one row per browser/device install)."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    p256dh: Mapped[str] = mapped_column(String(255), nullable=False)
    auth: Mapped[str] = mapped_column(String(255), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(255))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ── Increment 10: teacher voice + spaced repetition ───────────────────────


class LectureAudio(Base, TimestampMixin):
    """Synthesized narration for one lecture segment (worker → Postgres →
    app server; the GPU worker has no file path to app storage)."""

    __tablename__ = "lecture_audio"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    artifact_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False
    )
    segment_index: Mapped[int] = mapped_column(nullable=False)
    audio: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    mime: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_ms: Mapped[int] = mapped_column(nullable=False)
    voice: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("artifact_id", "segment_index", name="uq_lecture_audio_segment"),
    )


class LectureCheckpointResult(Base):
    """The student's answer to an in-lecture checkpoint question."""

    __tablename__ = "lecture_checkpoint_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    artifact_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False
    )
    segment_index: Mapped[int] = mapped_column(nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_checkpoint_results_artifact", "artifact_id", "segment_index"),
    )


class CardReview(Base):
    """SM-2-lite scheduling state, one row per flashcard."""

    __tablename__ = "card_reviews"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    flashcard_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("flashcards.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    interval_days: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    ease: Mapped[float] = mapped_column(Float, nullable=False, default=2.5)
    reps: Mapped[int] = mapped_column(nullable=False, default=0)
    lapses: Mapped[int] = mapped_column(nullable=False, default=0)
    last_rating: Mapped[str | None] = mapped_column(String(8))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_card_reviews_due", "due_date"),)


class SpeechClip(Base, TimestampMixin):
    """Synthesized audio for one chat message (teacher voice replies)."""

    __tablename__ = "speech_clips"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_message_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    audio: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    mime: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_ms: Mapped[int] = mapped_column(nullable=False)
    voice: Mapped[str] = mapped_column(String(64), nullable=False)


class VoicePreview(Base, TimestampMixin):
    """Voice-lab A/B sample: one line rendered by one voice variant."""

    __tablename__ = "voice_previews"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    variant: Mapped[str] = mapped_column(String(16), nullable=False)  # base|tuned
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    audio: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    mime: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_ms: Mapped[int] = mapped_column(nullable=False)

    __table_args__ = (
        UniqueConstraint("variant", "text", name="uq_voice_previews_variant_text"),
    )
