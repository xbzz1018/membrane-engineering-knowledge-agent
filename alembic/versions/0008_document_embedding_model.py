"""Track the embedding model used for each indexed document."""

import sqlalchemy as sa

from alembic import op

revision = "0008_document_embedding_model"
down_revision = "0007_review_issues"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("documents")}
    if "embedding_model" not in columns:
        op.add_column(
            "documents",
            sa.Column("embedding_model", sa.String(128), nullable=False, server_default=""),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("documents")}
    if "embedding_model" in columns:
        op.drop_column("documents", "embedding_model")
