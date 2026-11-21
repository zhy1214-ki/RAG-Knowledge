"""Real-usage-only persistent guard tables; not on the Mock migration path."""
from alembic import op
import sqlalchemy as sa

revision = "r1_001"
down_revision = "001"


def upgrade():
    op.create_table("real_usage_guard", sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stopped", sa.Boolean(), nullable=False), sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("historical_requests", sa.Integer(), nullable=False))
    op.create_table("real_usage_calls", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False), sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("day", sa.String(10), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("estimated_input", sa.Integer(), nullable=False), sa.Column("reserved_output", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False), sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("charge_cny", sa.Numeric(18, 8), nullable=False))
    op.create_index("ix_real_usage_calls_created_at", "real_usage_calls", ["created_at"])
    op.create_index("ix_real_usage_calls_day", "real_usage_calls", ["day"])
    op.create_table("real_usage_operations", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False), sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False))
    op.create_index("ix_real_usage_operations_fingerprint", "real_usage_operations", ["fingerprint"])


def downgrade():
    for table in ("real_usage_operations", "real_usage_calls", "real_usage_guard"):
        op.drop_table(table)