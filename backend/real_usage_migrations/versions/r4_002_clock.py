"""Add durable clock protection without changing historical calls or budgets."""
from alembic import op
import sqlalchemy as sa

revision = "r4_002"
down_revision = "r1_001"


def upgrade():
    op.add_column("real_usage_guard", sa.Column("last_observed_at", sa.Float(), server_default="0", nullable=False))
    op.add_column("real_usage_guard", sa.Column("clock_epoch", sa.Integer(), server_default="0", nullable=False))


def downgrade():
    op.drop_column("real_usage_guard", "clock_epoch")
    op.drop_column("real_usage_guard", "last_observed_at")
