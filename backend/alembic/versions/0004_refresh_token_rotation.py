"""Separate token rotation from revocation.

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("refresh_tokens", sa.Column("rotated_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("refresh_tokens", "rotated_at")
