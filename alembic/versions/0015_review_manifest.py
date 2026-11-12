"""Immutable review evidence snapshots outside Temporal history."""

import sqlalchemy as sa

from alembic import op

revision = "0015_review_manifest"
down_revision = "0014_document_business_metadata"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("review_manifests",
        sa.Column("review_id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("review_manifests")
