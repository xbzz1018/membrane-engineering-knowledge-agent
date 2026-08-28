"""Move derived image SHA metadata onto EvidenceUnit rows."""

import sqlalchemy as sa

from alembic import op

revision = "0005_fix_evidence_asset_sha"
down_revision = "0004_enterprise_review_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    chunk_columns = {column["name"] for column in inspector.get_columns("document_chunks")}
    if "asset_sha256" not in chunk_columns:
        op.add_column(
            "document_chunks",
            sa.Column("asset_sha256", sa.String(64), nullable=False, server_default=""),
        )
    document_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("documents")}
    if "asset_sha256" in document_columns:
        op.drop_column("documents", "asset_sha256")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    document_columns = {column["name"] for column in inspector.get_columns("documents")}
    if "asset_sha256" not in document_columns:
        op.add_column("documents", sa.Column("asset_sha256", sa.String(64), nullable=False, server_default=""))
    chunk_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("document_chunks")}
    if "asset_sha256" in chunk_columns:
        op.drop_column("document_chunks", "asset_sha256")
