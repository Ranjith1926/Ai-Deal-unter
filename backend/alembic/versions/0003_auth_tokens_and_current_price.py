"""Auth token tables and denormalised current price on listings.

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("product_platforms", sa.Column("current_price", sa.Numeric(12, 2)))
    op.add_column("product_platforms", sa.Column("current_mrp", sa.Numeric(12, 2)))
    op.add_column("product_platforms", sa.Column("price_captured_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        op.f("ck_product_platforms_current_price_non_negative"),
        "product_platforms",
        "current_price IS NULL OR current_price >= 0",
    )
    op.create_index("ix_product_platforms_price", "product_platforms", ["current_price"])

    # Backfill from existing history: latest observation per listing.
    op.execute(
        """
        UPDATE product_platforms pl
        SET current_price = CASE WHEN lp.availability = 'in_stock' THEN lp.price END,
            current_mrp = lp.mrp,
            price_captured_at = lp.captured_at
        FROM (
            SELECT DISTINCT ON (product_platform_id)
                   product_platform_id, price, mrp, availability, captured_at
            FROM product_prices
            ORDER BY product_platform_id, captured_at DESC
        ) lp
        WHERE lp.product_platform_id = pl.id
        """
    )

    for table, extra_col in (("refresh_tokens", "revoked_at"), ("password_reset_tokens", "used_at")):
        op.create_table(
            table,
            sa.Column("id", sa.BigInteger, nullable=False),
            sa.Column("user_id", sa.BigInteger, nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(extra_col, sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
            sa.UniqueConstraint("token_hash", name=op.f(f"uq_{table}_token_hash")),
            sa.ForeignKeyConstraint(
                ["user_id"], ["users.id"], name=op.f(f"fk_{table}_user_id_users"), ondelete="CASCADE"
            ),
        )
        op.create_index(f"ix_{table}_user", table, ["user_id"])


def downgrade() -> None:
    op.drop_table("password_reset_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("ix_product_platforms_price", "product_platforms")
    op.drop_constraint(op.f("ck_product_platforms_current_price_non_negative"), "product_platforms")
    op.drop_column("product_platforms", "price_captured_at")
    op.drop_column("product_platforms", "current_mrp")
    op.drop_column("product_platforms", "current_price")
