"""Add editable enterprise catalog and frontend contract fields."""

import sqlalchemy as sa

from alembic import op

revision = "0012_frontend_contract"
down_revision = "0011_mcp_gateway"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    for table in ("material_specs", "price_records"):
        columns = _columns(table)
        additions = (
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by", sa.String(64), nullable=False, server_default="seed"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        for column in additions:
            if column.name not in columns:
                op.add_column(table, column)
        op.execute(sa.text(
            f"UPDATE {table} SET status='active', lock_version=1, created_by='seed' "
            "WHERE status IS NULL OR status=''"
        ))

    if "ix_material_specs_tenant_status_visibility" not in _indexes("material_specs"):
        op.create_index(
            "ix_material_specs_tenant_status_visibility",
            "material_specs",
            ["tenant_id", "status", "visibility"],
        )
    if "ix_price_records_tenant_project_status_visibility" not in _indexes("price_records"):
        op.create_index(
            "ix_price_records_tenant_project_status_visibility",
            "price_records",
            ["tenant_id", "project_id", "status", "visibility"],
        )


def downgrade() -> None:
    for table, index in (
        ("price_records", "ix_price_records_tenant_project_status_visibility"),
        ("material_specs", "ix_material_specs_tenant_status_visibility"),
    ):
        if index in _indexes(table):
            op.drop_index(index, table_name=table)
    for table in ("price_records", "material_specs"):
        columns = _columns(table)
        for name in ("updated_at", "created_at", "created_by", "lock_version", "status"):
            if name in columns:
                op.drop_column(table, name)
