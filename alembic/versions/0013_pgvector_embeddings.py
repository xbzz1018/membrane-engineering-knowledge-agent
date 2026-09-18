"""Move document and confirmed-memory vector indexes into PostgreSQL."""

from alembic import op

revision = "0013_pgvector_embeddings"
down_revision = "0012_frontend_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("""
        CREATE TABLE IF NOT EXISTS document_embeddings (
            id VARCHAR(128) PRIMARY KEY,
            embedding vector(1024) NOT NULL,
            text TEXT NOT NULL,
            document_id VARCHAR(64) NOT NULL,
            filename VARCHAR(512) NOT NULL,
            page_number INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT '',
            project_id VARCHAR(128) NOT NULL DEFAULT '',
            tenant_id VARCHAR(64) NOT NULL DEFAULT '',
            classification VARCHAR(16) NOT NULL DEFAULT 'public',
            location VARCHAR(512) NOT NULL DEFAULT '',
            heading_path VARCHAR(1000) NOT NULL DEFAULT '',
            sheet_name VARCHAR(256) NOT NULL DEFAULT '',
            anchor VARCHAR(128) NOT NULL DEFAULT '',
            source_kind VARCHAR(32) NOT NULL DEFAULT 'text',
            ocr_used BOOLEAN NOT NULL DEFAULT FALSE,
            asset_sha256 VARCHAR(64) NOT NULL DEFAULT '',
            embedding_model VARCHAR(128) NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_document_embeddings_scope
        ON document_embeddings (tenant_id, project_id, classification, embedding_model)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_document_embeddings_document
        ON document_embeddings (document_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_document_embeddings_hnsw
        ON document_embeddings USING hnsw (embedding vector_cosine_ops)
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS memory_embeddings (
            id VARCHAR(128) PRIMARY KEY,
            embedding vector(1024) NOT NULL,
            user_id VARCHAR(64) NOT NULL,
            kind VARCHAR(32) NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT '',
            tenant_id VARCHAR(64) NOT NULL DEFAULT '',
            project_id VARCHAR(128) NOT NULL DEFAULT '',
            scope VARCHAR(16) NOT NULL DEFAULT 'user',
            embedding_model VARCHAR(128) NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_memory_embeddings_scope
        ON memory_embeddings (tenant_id, user_id, project_id, scope, embedding_model)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_memory_embeddings_hnsw
        ON memory_embeddings USING hnsw (embedding vector_cosine_ops)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS memory_embeddings")
    op.execute("DROP TABLE IF EXISTS document_embeddings")

