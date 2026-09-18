"""Persist safe MCP tool audits and idempotency results."""

import sqlalchemy as sa

from alembic import op

revision = "0011_mcp_gateway"
down_revision = "0010_prompt_and_review_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("mcp_tool_calls"):
        op.create_table(
            "mcp_tool_calls",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("user_id", sa.String(64), nullable=False),
            sa.Column("client_id", sa.String(128), nullable=False, server_default=""),
            sa.Column("project_id", sa.String(128), nullable=False, server_default=""),
            sa.Column("tool_name", sa.String(128), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("duration_ms", sa.Float(), nullable=False, server_default="0"),
            sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("result_ref", sa.String(256), nullable=False, server_default=""),
            sa.Column("error_type", sa.String(128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if not inspector.has_table("mcp_idempotency"):
        op.create_table(
            "mcp_idempotency",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("user_id", sa.String(64), nullable=False),
            sa.Column("tool_name", sa.String(128), nullable=False),
            sa.Column("idempotency_key", sa.String(128), nullable=False),
            sa.Column("request_hash", sa.String(64), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("result_ref", sa.String(256), nullable=False, server_default=""),
            sa.Column("result_payload", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "tenant_id", "user_id", "tool_name", "idempotency_key",
                name="uq_mcp_idempotency_scope",
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in ("mcp_idempotency", "mcp_tool_calls"):
        if inspector.has_table(table):
            op.drop_table(table)
