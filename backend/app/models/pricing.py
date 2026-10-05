"""Append-only price history, offers and calculated scores."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.catalog import AVAILABILITY_VALUES


class ProductPrice(Base):
    """One price observation. Rows are never updated or overwritten."""

    __tablename__ = "product_prices"
    __table_args__ = (
        CheckConstraint("price IS NULL OR price >= 0", name="price_non_negative"),
        CheckConstraint("mrp IS NULL OR mrp >= 0", name="mrp_non_negative"),
        CheckConstraint(f"availability IN {AVAILABILITY_VALUES}", name="availability_valid"),
        CheckConstraint("data_quality IN ('verified','estimated')", name="data_quality_valid"),
        # A missing price is only acceptable when the item is not purchasable.
        CheckConstraint("price IS NOT NULL OR availability <> 'in_stock'", name="in_stock_has_price"),
        # Serves "history for a listing, newest first" and range scans.
        Index("ix_product_prices_listing_captured", "product_platform_id", text("captured_at DESC")),
        Index("ix_product_prices_captured", "captured_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_platform_id: Mapped[int] = mapped_column(
        ForeignKey("product_platforms.id", ondelete="CASCADE"), nullable=False
    )
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    mrp: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), server_default="INR", nullable=False)
    availability: Mapped[str] = mapped_column(String(20), server_default="unknown", nullable=False)
    seller_name: Mapped[str | None] = mapped_column(String(200))
    # 'verified' = reported by the provider; 'estimated' = derived by us.
    data_quality: Mapped[str] = mapped_column(String(12), server_default="verified", nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProductOffer(Base):
    __tablename__ = "product_offers"
    __table_args__ = (
        CheckConstraint(
            "offer_type IN ('bank','exchange','coupon','cashback','no_cost_emi','other')",
            name="offer_type_valid",
        ),
        CheckConstraint("discount_amount IS NULL OR discount_amount >= 0", name="discount_non_negative"),
        CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
            name="valid_range",
        ),
        Index("ix_product_offers_listing_captured", "product_platform_id", text("captured_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_platform_id: Mapped[int] = mapped_column(
        ForeignKey("product_platforms.id", ondelete="CASCADE"), nullable=False
    )
    offer_type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProductScore(Base):
    """Precomputed scores so reads never recompute history. One row per calculation."""

    __tablename__ = "product_scores"
    __table_args__ = (
        CheckConstraint("deal_score IS NULL OR (deal_score BETWEEN 0 AND 100)", name="deal_score_range"),
        CheckConstraint("value_score IS NULL OR (value_score BETWEEN 0 AND 100)", name="value_score_range"),
        Index("ix_product_scores_product_calculated", "product_id", text("calculated_at DESC")),
        Index("ix_product_scores_calculated_deal", text("calculated_at DESC"), text("deal_score DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    deal_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    value_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Stored factor breakdown + explanation inputs; explanations are built only from this data.
    score_reason: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
