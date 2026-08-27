"""Create engineering assistant tables."""

import sqlalchemy as sa

from alembic import op

revision = "0001_engineering_schema"
down_revision = None
branch_labels = None
depends_on = None


def _create_if_missing(name: str, *columns) -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(name):
        op.create_table(name, *columns)


def upgrade() -> None:
    _create_if_missing(
        "documents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parser", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_if_missing(
        "document_chunks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    for name in ("engineering_cases", "material_specs", "price_records"):
        _create_if_missing(name, sa.Column("id", sa.String(128), primary_key=True), sa.Column("payload", sa.Text(), nullable=False))
    _create_if_missing(
        "conversations",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_if_missing(
        "memory_items",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_if_missing(
        "outbox_events",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("aggregate_id", sa.String(128), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_if_missing(
        "inbox_events",
        sa.Column("event_id", sa.String(128), primary_key=True),
        sa.Column("consumer", sa.String(128), primary_key=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for name in ("inbox_events", "outbox_events", "memory_items", "conversations", "price_records", "material_specs", "engineering_cases", "document_chunks", "documents"):
        op.drop_table(name)
