"""Initial V1 schema, frozen independently of runtime model definitions."""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None


def pk():
    return sa.Column("id", sa.String(36), primary_key=True)


def ref(name, target):
    return sa.Column(name, sa.String(36), sa.ForeignKey(target, ondelete="CASCADE"), nullable=False)


def created():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)


def upgrade():
    op.create_table("users", pk(), sa.Column("username", sa.String(64), nullable=False, unique=True),
                    sa.Column("password_hash", sa.String(256), nullable=False), created())
    op.create_table("knowledge_bases", pk(), ref("owner_id", "users.id"),
                    sa.Column("name", sa.String(120), nullable=False), sa.Column("description", sa.Text(), nullable=False),
                    created(), sa.UniqueConstraint("owner_id", "name"))
    op.create_index("ix_knowledge_bases_owner_id", "knowledge_bases", ["owner_id"])
    op.create_table("documents", pk(), ref("knowledge_base_id", "knowledge_bases.id"),
                    sa.Column("name", sa.String(255), nullable=False), sa.Column("file_path", sa.Text(), nullable=False),
                    sa.Column("file_type", sa.String(12), nullable=False), sa.Column("size", sa.Integer(), nullable=False),
                    sa.Column("status", sa.String(20), nullable=False), sa.Column("progress", sa.Integer(), nullable=False),
                    sa.Column("chunk_count", sa.Integer(), nullable=False), sa.Column("error_code", sa.String(64)), created())
    op.create_index("ix_documents_knowledge_base_id", "documents", ["knowledge_base_id"])
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_table("document_chunks", sa.Column("chunk_id", sa.String(36), primary_key=True),
                    ref("document_id", "documents.id"), ref("knowledge_base_id", "knowledge_bases.id"),
                    sa.Column("text", sa.Text(), nullable=False), sa.Column("source_name", sa.String(255), nullable=False),
                    sa.Column("source_location", sa.JSON(), nullable=False), sa.Column("chunk_index", sa.Integer(), nullable=False),
                    sa.UniqueConstraint("document_id", "chunk_index"))
    op.create_index("ix_chunks_kb_doc", "document_chunks", ["knowledge_base_id", "document_id"])
    op.create_table("chat_sessions", pk(), ref("owner_id", "users.id"), ref("knowledge_base_id", "knowledge_bases.id"),
                    sa.Column("title", sa.String(120), nullable=False), created())
    op.create_index("ix_chat_sessions_owner_id", "chat_sessions", ["owner_id"])
    op.create_index("ix_chat_sessions_knowledge_base_id", "chat_sessions", ["knowledge_base_id"])
    op.create_table("chat_messages", pk(), ref("session_id", "chat_sessions.id"),
                    sa.Column("role", sa.String(16), nullable=False), sa.Column("content", sa.Text(), nullable=False),
                    sa.Column("citations", sa.JSON(), nullable=False), created())
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])


def downgrade():
    for name in ("chat_messages", "chat_sessions", "document_chunks", "documents", "knowledge_bases", "users"):
        op.drop_table(name)
