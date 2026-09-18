"""Persist structured engineering review issues."""

import sqlalchemy as sa

from alembic import op

revision = "0007_review_issues"
down_revision = "0006_agent_run_business_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("package_reviews")}
    if "issues" not in columns:
        op.add_column(
            "package_reviews",
            sa.Column("issues", sa.Text(), nullable=False, server_default="[]"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("package_reviews")}
    if "issues" in columns:
        op.drop_column("package_reviews", "issues")
