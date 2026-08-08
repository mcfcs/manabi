"""Documents, pages, elements, chunks (with FTS).

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-09

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "module_id",
            sa.BigInteger(),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Enum("pdf", "pptx", name="document_kind"), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column(
            "extract_status",
            sa.Enum("pending", "processing", "ready", "failed", name="extract_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("extract_stage", sa.String(32)),
        sa.Column("error", sa.Text()),
        sa.Column("page_count", sa.Integer()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("module_id", "content_hash", name="uq_documents_module_hash"),
    )
    op.create_index("ix_documents_module_id", "documents", ["module_id"])

    op.create_table(
        "document_pages",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "document_id",
            sa.BigInteger(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(512)),
        sa.Column("speaker_notes", sa.Text()),
        sa.Column("render_path", sa.String(1024)),
        sa.Column("thumb_path", sa.String(1024)),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.UniqueConstraint("document_id", "page_no", name="uq_document_pages_doc_page"),
    )

    op.create_table(
        "doc_elements",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "document_id",
            sa.BigInteger(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "page_id",
            sa.BigInteger(),
            sa.ForeignKey("document_pages.id", ondelete="CASCADE"),
        ),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("element_type", sa.String(32), nullable=False),
        sa.Column("text_content", sa.Text()),
        sa.Column("table_json", postgresql.JSONB()),
        sa.Column("asset_path", sa.String(1024)),
        sa.Column("bbox", postgresql.JSONB()),
    )
    op.create_index("ix_doc_elements_document_id", "doc_elements", ["document_id", "order_index"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "module_id",
            sa.BigInteger(),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.BigInteger(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("element_ids", postgresql.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("heading_path", sa.Text()),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_chunks_module_id", "chunks", ["module_id"])
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.execute(
        """
        ALTER TABLE chunks ADD COLUMN tsv tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english', coalesce(heading_path, '') || ' ' || text)
        ) STORED
        """
    )
    op.execute("CREATE INDEX ix_chunks_tsv ON chunks USING gin (tsv)")


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_table("doc_elements")
    op.drop_table("document_pages")
    op.drop_table("documents")
    sa.Enum(name="extract_status").drop(op.get_bind())
    sa.Enum(name="document_kind").drop(op.get_bind())
