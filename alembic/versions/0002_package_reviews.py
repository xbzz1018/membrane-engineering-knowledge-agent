"""Persist package review reports and evidence."""

import sqlalchemy as sa

from alembic import op

revision = "0002_package_reviews"
down_revision = "0001_engineering_schema"
branch_labels = None
depends_on = None


def _create_if_missing(name: str, *columns) -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(name):
        op.create_table(name, *columns)


def upgrade() -> None:
    _create_if_missing(
        "package_reviews",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("engine", sa.String(32), nullable=False),
        sa.Column("report", sa.Text(), nullable=False),
        sa.Column("conflicts", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create_if_missing(
        "package_review_evidence",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("review_id", sa.String(128), nullable=False),
        sa.Column("source_id", sa.String(256), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("package_review_evidence")
    op.drop_table("package_reviews")
