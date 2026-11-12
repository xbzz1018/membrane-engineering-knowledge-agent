"""Fence document writes by Temporal Activity execution and attempt."""

import sqlalchemy as sa

from alembic import op

revision = "0016_document_ingest_claims"
down_revision = "0015_review_manifest"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("document_ingest_claims",
        sa.Column("document_id", sa.String(64), primary_key=True),
        sa.Column("execution_id", sa.String(256), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("document_ingest_claims")
