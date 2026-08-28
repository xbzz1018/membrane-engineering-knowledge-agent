"""Enterprise review platform, normalized evidence, and Temporal-only batches."""

import sqlalchemy as sa

from alembic import op

revision = "0004_enterprise_review_platform"
down_revision = "0003_kafka_outbox_inbox"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in _inspector().get_columns(table)}


def _add(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _create(name: str, *columns, **kwargs) -> None:
    if not _inspector().has_table(name):
        op.create_table(name, *columns, **kwargs)


def upgrade() -> None:
    _create(
        "tenants",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("username", sa.String(128), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create(
        "projects",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("daily_token_limit", sa.Integer(), nullable=False, server_default="1000000"),
        sa.Column("monthly_cost_limit_micros", sa.Integer(), nullable=False, server_default="100000000"),
        sa.Column("max_concurrent_reviews", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("used_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved_cost_micros", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("used_cost_micros", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("token_usage_date", sa.String(10), nullable=False, server_default=""),
        sa.Column("cost_usage_month", sa.String(7), nullable=False, server_default=""),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create(
        "project_members",
        sa.Column("project_id", sa.String(128), primary_key=True),
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    for column in (
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="membrane-company"),
        sa.Column("project_id", sa.String(128), nullable=False, server_default="demo-project"),
        sa.Column("sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("data_classification", sa.String(16), nullable=False, server_default="public"),
        sa.Column("parse_method", sa.String(16), nullable=False, server_default="auto"),
        sa.Column("parser_version", sa.String(64), nullable=False, server_default=""),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("error_type", sa.String(128), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ):
        _add("documents", column)
    op.execute("UPDATE documents SET updated_at = created_at WHERE updated_at IS NULL")
    index_names = {index["name"] for index in _inspector().get_indexes("documents")}
    if "uq_document_project_sha_version" not in index_names:
        op.create_index(
            "uq_document_project_sha_version",
            "documents",
            ["project_id", "sha256", "version"],
            unique=True,
            postgresql_where=sa.text("sha256 <> ''"),
            sqlite_where=sa.text("sha256 <> ''"),
        )

    for column in (
        sa.Column("location", sa.String(512), nullable=False, server_default=""),
        sa.Column("heading_path", sa.String(1000), nullable=False, server_default=""),
        sa.Column("sheet_name", sa.String(256), nullable=False, server_default=""),
        sa.Column("anchor", sa.String(128), nullable=False, server_default=""),
        sa.Column("source_kind", sa.String(32), nullable=False, server_default="text"),
        sa.Column("ocr_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="processed"),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("asset_sha256", sa.String(64), nullable=False, server_default=""),
    ):
        _add("document_chunks", column)

    normalized = {
        "engineering_cases": [
            sa.Column("title", sa.String(512), nullable=False, server_default=""),
            sa.Column("structure_type", sa.String(256), nullable=False, server_default=""),
            sa.Column("membrane_material", sa.String(256), nullable=False, server_default=""),
            sa.Column("application", sa.String(512), nullable=False, server_default=""),
            sa.Column("year", sa.Integer(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=False, server_default=""),
            sa.Column("source_version", sa.String(128), nullable=False, server_default=""),
            sa.Column("synthetic", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("search_text", sa.Text(), nullable=False, server_default=""),
        ],
        "material_specs": [
            sa.Column("manufacturer", sa.String(256), nullable=False, server_default=""),
            sa.Column("material", sa.String(256), nullable=False, server_default=""),
            sa.Column("product_reference", sa.String(128), nullable=False, server_default=""),
            sa.Column("specification", sa.Text(), nullable=False, server_default=""),
            sa.Column("application", sa.Text(), nullable=False, server_default=""),
            sa.Column("source_url", sa.Text(), nullable=False, server_default=""),
            sa.Column("source_version", sa.String(128), nullable=False, server_default=""),
            sa.Column("synthetic", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("search_text", sa.Text(), nullable=False, server_default=""),
        ],
        "price_records": [
            sa.Column("material", sa.String(256), nullable=False, server_default=""),
            sa.Column("specification", sa.Text(), nullable=False, server_default=""),
            sa.Column("unit", sa.String(64), nullable=False, server_default=""),
            sa.Column("min_price", sa.Float(), nullable=True),
            sa.Column("max_price", sa.Float(), nullable=True),
            sa.Column("region", sa.String(128), nullable=False, server_default=""),
            sa.Column("effective_date", sa.String(32), nullable=False, server_default=""),
            sa.Column("currency", sa.String(16), nullable=False, server_default=""),
            sa.Column("source_url", sa.Text(), nullable=False, server_default=""),
            sa.Column("source_version", sa.String(128), nullable=False, server_default=""),
            sa.Column("synthetic", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("search_text", sa.Text(), nullable=False, server_default=""),
        ],
    }
    for table, columns in normalized.items():
        for column in columns:
            _add(table, column)
        op.execute(sa.text(f"UPDATE {table} SET search_text = payload WHERE search_text = ''"))

    for column in (
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="membrane-company"),
        sa.Column("project_id", sa.String(128), nullable=True),
        sa.Column("scope", sa.String(16), nullable=False, server_default="user"),
        sa.Column("source_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="confirmed"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ):
        _add("memory_items", column)
    op.execute("UPDATE memory_items SET updated_at = created_at, confirmed_at = created_at WHERE updated_at IS NULL")

    for column in (
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="membrane-company"),
        sa.Column("project_id", sa.String(128), nullable=False, server_default="demo-project"),
        sa.Column("workflow_id", sa.String(256), nullable=False, server_default=""),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ):
        _add("batch_imports", column)
    op.execute("UPDATE batch_imports SET updated_at = created_at WHERE updated_at IS NULL")

    for column in (
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="membrane-company"),
        sa.Column("worker_results", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("usage", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("human_review_required", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
    ):
        _add("package_reviews", column)

    _create(
        "agent_runs",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("run_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False, server_default=""),
        sa.Column("provider", sa.String(64), nullable=False, server_default=""),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("finish_reason", sa.String(32), nullable=False, server_default=""),
        sa.Column("error_type", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create(
        "agent_steps",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("step_name", sa.String(128), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("error_type", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _create(
        "budget_reservations",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("workflow_id", sa.String(256), nullable=False, unique=True),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("actual_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_micros", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actual_cost_micros", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    for obsolete in ("outbox_events", "inbox_events"):
        if _inspector().has_table(obsolete):
            op.drop_table(obsolete)


def downgrade() -> None:
    for name in ("budget_reservations", "agent_steps", "agent_runs", "project_members", "projects", "users", "tenants"):
        if _inspector().has_table(name):
            op.drop_table(name)
