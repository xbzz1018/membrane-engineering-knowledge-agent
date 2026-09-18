"""Add enterprise ownership to material and price catalogs."""

import sqlalchemy as sa

from alembic import op

revision = "0009_catalog_scope"
down_revision = "0008_document_embedding_model"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    for table in ("material_specs", "price_records"):
        columns = _columns(table)
        if "tenant_id" not in columns:
            op.add_column(
                table,
                sa.Column("tenant_id", sa.String(64), nullable=False, server_default="membrane-company"),
            )
        if "visibility" not in columns:
            op.add_column(
                table,
                sa.Column("visibility", sa.String(16), nullable=False, server_default="public"),
            )
    if "project_id" not in _columns("price_records"):
        op.add_column(
            "price_records",
            sa.Column("project_id", sa.String(128), nullable=False, server_default=""),
        )
    op.execute(sa.text("DELETE FROM engineering_cases WHERE id LIKE 'fixture-case-%'"))


def downgrade() -> None:
    if "project_id" in _columns("price_records"):
        op.drop_column("price_records", "project_id")
    for table in ("price_records", "material_specs"):
        columns = _columns(table)
        if "visibility" in columns:
            op.drop_column(table, "visibility")
        if "tenant_id" in columns:
            op.drop_column(table, "tenant_id")
