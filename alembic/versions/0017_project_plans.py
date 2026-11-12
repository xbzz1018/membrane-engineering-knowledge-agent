"""Versioned project plans, review binding, durable decisions and artifact identity.

Table definitions below are a frozen migration snapshot.
"""

from sqlalchemy import Column, DateTime, Integer, String, Table, Text, UniqueConstraint

from alembic import op

revision = "0017_project_plans"
down_revision = "0016_document_ingest_claims"
branch_labels = None
depends_on = None



def define_plan_tables(metadata):
    plans = Table(
        "project_plans", metadata,
        Column("id", String(64), primary_key=True),
        Column("tenant_id", String(64), nullable=False),
        Column("project_id", String(128), nullable=False),
        Column("created_by", String(64), nullable=False),
        Column("request_id", String(128), nullable=False),
        Column("request_hash", String(64), nullable=False),
        Column("current_version", Integer, nullable=False),
        Column("lock_version", Integer, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("tenant_id", "project_id", "created_by", "request_id", name="uq_plan_request"),
    )
    versions = Table(
        "project_plan_versions", metadata,
        Column("plan_id", String(64), primary_key=True),
        Column("version", Integer, primary_key=True),
        Column("parent_version", Integer, nullable=True),
        Column("request_id", String(128), nullable=False),
        Column("request_hash", String(64), nullable=False),
        Column("status", String(32), nullable=False),
        Column("requirements", Text, nullable=False),
        Column("content", Text, nullable=True),
        Column("content_hash", String(64), nullable=False),
        Column("manifest", Text, nullable=True),
        Column("manifest_hash", String(64), nullable=False),
        Column("usage", Text, nullable=False),
        Column("workflow_id", String(128), nullable=False),
        Column("execution_id", String(256), nullable=False),
        Column("attempt", Integer, nullable=False),
        Column("error_type", String(128), nullable=False),
        Column("reason", String(1000), nullable=False),
        Column("created_by", String(64), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("plan_id", "request_id", name="uq_plan_revision_request"),
    )
    reviews = Table(
        "project_plan_reviews", metadata,
        Column("id", String(64), primary_key=True),
        Column("plan_id", String(64), nullable=False),
        Column("version", Integer, nullable=False),
        Column("content_hash", String(64), nullable=False),
        Column("manifest_hash", String(64), nullable=False),
        Column("passed", Integer, nullable=False),
        Column("result", Text, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("plan_id", "version", name="uq_plan_review_version"),
    )
    decisions = Table(
        "project_plan_decisions", metadata,
        Column("command_id", String(128), primary_key=True),
        Column("plan_id", String(64), nullable=False),
        Column("version", Integer, nullable=False),
        Column("review_id", String(64), nullable=False),
        Column("content_hash", String(64), nullable=False),
        Column("manifest_hash", String(64), nullable=False),
        Column("actor", String(64), nullable=False),
        Column("decision", String(16), nullable=False),
        Column("reason", String(1000), nullable=False),
        Column("request_hash", String(64), nullable=False),
        Column("consumed", Integer, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("plan_id", "version", name="uq_plan_decision_version"),
    )
    artifacts = Table(
        "project_plan_artifacts", metadata,
        Column("id", String(64), primary_key=True),
        Column("plan_id", String(64), nullable=False),
        Column("version", Integer, nullable=False),
        Column("content_hash", String(64), nullable=False),
        Column("manifest_hash", String(64), nullable=False),
        Column("format", String(8), nullable=False),
        Column("template_version", String(32), nullable=False),
        Column("renderer_version", String(32), nullable=False),
        Column("status", String(16), nullable=False),
        Column("execution_id", String(256), nullable=False),
        Column("attempt", Integer, nullable=False),
        Column("object_key", Text, nullable=False),
        Column("sha256", String(64), nullable=False),
        Column("byte_size", Integer, nullable=False),
        Column("error_type", String(128), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("plan_id", "version", "format", "template_version", "renderer_version",
                         name="uq_plan_artifact_identity"),
    )
    return plans, versions, reviews, decisions, artifacts


def upgrade():
    from sqlalchemy import MetaData

    tables = define_plan_tables(MetaData())
    for table in tables:
        table.create(op.get_bind())


def downgrade():
    for name in ("project_plan_artifacts", "project_plan_decisions", "project_plan_reviews",
                 "project_plan_versions", "project_plans"):
        op.drop_table(name)
