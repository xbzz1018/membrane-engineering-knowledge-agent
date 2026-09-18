"""Link Agent execution summaries to review or session business IDs."""

import sqlalchemy as sa

from alembic import op

revision = "0006_agent_run_business_link"
down_revision = "0005_fix_evidence_asset_sha"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("agent_runs")}
    if "business_id" not in columns:
        op.add_column(
            "agent_runs",
            sa.Column("business_id", sa.String(128), nullable=False, server_default=""),
        )
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("agent_runs")}
    if "ix_agent_runs_business_id" not in indexes:
        op.create_index("ix_agent_runs_business_id", "agent_runs", ["business_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("agent_runs")}
    if "ix_agent_runs_business_id" in indexes:
        op.drop_index("ix_agent_runs_business_id", table_name="agent_runs")
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("agent_runs")}
    if "business_id" in columns:
        op.drop_column("agent_runs", "business_id")
