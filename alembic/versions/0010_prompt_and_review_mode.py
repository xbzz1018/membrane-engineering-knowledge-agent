"""Track review mode and prompt versions."""

import sqlalchemy as sa

from alembic import op

revision = "0010_prompt_and_review_mode"
down_revision = "0009_catalog_scope"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "review_mode" not in _columns("package_reviews"):
        op.add_column(
            "package_reviews",
            sa.Column("review_mode", sa.String(16), nullable=False, server_default="full"),
        )
    agent_columns = _columns("agent_runs")
    for column in (
        sa.Column("prompt_name", sa.String(64), nullable=False, server_default=""),
        sa.Column("prompt_version", sa.String(32), nullable=False, server_default=""),
        sa.Column("prompt_sha256", sa.String(64), nullable=False, server_default=""),
    ):
        if column.name not in agent_columns:
            op.add_column("agent_runs", column)


def downgrade() -> None:
    for name in ("prompt_sha256", "prompt_version", "prompt_name"):
        if name in _columns("agent_runs"):
            op.drop_column("agent_runs", name)
    if "review_mode" in _columns("package_reviews"):
        op.drop_column("package_reviews", "review_mode")
