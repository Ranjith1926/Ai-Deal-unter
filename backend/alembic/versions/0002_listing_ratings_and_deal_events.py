"""Listing rating/review count and deal_events table.

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("product_platforms", sa.Column("rating", sa.Numeric(3, 2)))
    op.add_column("product_platforms", sa.Column("review_count", sa.Integer))
    op.create_check_constraint(
        op.f("ck_product_platforms_rating_range"),
        "product_platforms",
        "rating IS NULL OR (rating >= 0 AND rating <= 5)",
    )
    op.create_check_constraint(
        op.f("ck_product_platforms_reviews_non_negative"),
        "product_platforms",
        "review_count IS NULL OR review_count >= 0",
    )

    op.create_table(
        "deal_events",
        sa.Column("id", sa.BigInteger, nullable=False),
        sa.Column("product_id", sa.BigInteger, nullable=False),
        sa.Column("product_platform_id", sa.BigInteger),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("price", sa.Numeric(12, 2)),
        sa.Column("previous_price", sa.Numeric(12, 2)),
        sa.Column("deal_score", sa.Numeric(5, 2)),
        sa.Column("detail", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deal_events")),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name=op.f("fk_deal_events_product_id_products"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["product_platform_id"],
            ["product_platforms.id"],
            name=op.f("fk_deal_events_product_platform_id_product_platforms"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "event_type IN ('new_deal','price_drop','historical_low','deal_expired','back_in_stock')",
            name=op.f("ck_deal_events_event_type_valid"),
        ),
    )
    op.create_index("ix_deal_events_detected", "deal_events", [sa.text("detected_at DESC")])
    op.create_index("ix_deal_events_type_detected", "deal_events", ["event_type", sa.text("detected_at DESC")])
    op.create_index(
        "ix_deal_events_product_type_detected",
        "deal_events",
        ["product_id", "event_type", sa.text("detected_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("deal_events")
    op.drop_constraint(op.f("ck_product_platforms_reviews_non_negative"), "product_platforms")
    op.drop_constraint(op.f("ck_product_platforms_rating_range"), "product_platforms")
    op.drop_column("product_platforms", "review_count")
    op.drop_column("product_platforms", "rating")
