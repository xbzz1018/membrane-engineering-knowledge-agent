"""Explicit, attributed business identity and effective-date metadata."""

import sqlalchemy as sa

from alembic import op

revision = "0014_document_business_metadata"
down_revision = "0013_pgvector_embeddings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "document_business_metadata",
        sa.Column("document_id", sa.String(64), primary_key=True),
        sa.Column("engineering_model", sa.String(128), nullable=False),
        sa.Column("applicable_revision", sa.String(128), nullable=False),
        sa.Column("document_type", sa.String(16), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("source_note", sa.String(1000), nullable=False),
        sa.Column("declared_by", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_doc_business_identity", "document_business_metadata",
                    ["engineering_model", "applicable_revision", "document_type"])
    op.create_index("ix_doc_business_effective", "document_business_metadata", ["effective_from", "effective_to"])


def downgrade():
    op.drop_table("document_business_metadata")
