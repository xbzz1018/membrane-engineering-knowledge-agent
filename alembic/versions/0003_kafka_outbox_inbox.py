"""Add Kafka outbox relay, inbox status, and batch imports."""

import sqlalchemy as sa

from alembic import op

revision = "0003_kafka_outbox_inbox"
down_revision = "0002_package_reviews"
branch_labels = None
depends_on = None


def _column_names(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    outbox_columns = _column_names("outbox_events")
    if "topic" not in outbox_columns:
        op.add_column("outbox_events", sa.Column("topic", sa.String(256), nullable=False, server_default=""))
    if "publish_attempts" not in outbox_columns:
        op.add_column(
            "outbox_events",
            sa.Column("publish_attempts", sa.Integer(), nullable=False, server_default="0"),
        )
    if "last_error" not in outbox_columns:
        op.add_column("outbox_events", sa.Column("last_error", sa.Text(), nullable=True))

    inbox_columns = _column_names("inbox_events")
    if "status" not in inbox_columns:
        op.add_column(
            "inbox_events",
            sa.Column("status", sa.String(32), nullable=False, server_default="processed"),
        )
    if "attempts" not in inbox_columns:
        op.add_column("inbox_events", sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"))
    if "payload" not in inbox_columns:
        op.add_column("inbox_events", sa.Column("payload", sa.Text(), nullable=False, server_default="{}"))
    if "last_error" not in inbox_columns:
        op.add_column("inbox_events", sa.Column("last_error", sa.Text(), nullable=True))
    op.alter_column("inbox_events", "processed_at", existing_type=sa.DateTime(timezone=True), nullable=True)

    if not sa.inspect(op.get_bind()).has_table("batch_imports"):
        op.create_table(
            "batch_imports",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("document_count", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("batch_imports")
    for column in ("last_error", "payload", "attempts", "status"):
        op.drop_column("inbox_events", column)
    op.alter_column("inbox_events", "processed_at", existing_type=sa.DateTime(timezone=True), nullable=False)
    for column in ("last_error", "publish_attempts", "topic"):
        op.drop_column("outbox_events", column)
