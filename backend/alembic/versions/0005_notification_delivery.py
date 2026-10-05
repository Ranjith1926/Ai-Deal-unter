"""Delivery tracking for notifications and Web Push subscriptions.

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False))
    op.add_column("notifications", sa.Column("last_error", sa.String(300)))
    # Sensitive messages (password-reset links) are scrubbed once delivery finishes, successfully or not.
    op.add_column("notifications", sa.Column("is_sensitive", sa.Boolean(), server_default=sa.false(), nullable=False))

    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("endpoint", sa.String(1024), nullable=False, unique=True),
        sa.Column("p256dh", sa.String(256), nullable=False),
        sa.Column("auth", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_push_subscriptions_user", "push_subscriptions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_push_subscriptions_user", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
    op.drop_column("notifications", "is_sensitive")
    op.drop_column("notifications", "last_error")
    op.drop_column("notifications", "attempts")
