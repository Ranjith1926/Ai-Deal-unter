"""Categories, canonical products and their per-marketplace listings."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

AVAILABILITY_VALUES = "('in_stock','out_of_stock','discontinued','unknown')"


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(140), unique=True, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )


class Product(TimestampMixin, Base):
    """A canonical product *variant*.

    Variants (storage, RAM, colour, pack size) are separate rows, distinguished by
    ``variant_key``, so "iPhone 16 128GB" and "iPhone 16 256GB" are never merged.
    """

    __tablename__ = "products"
    __table_args__ = (
        # Identifiers are unique only when present.
        Index("uq_products_gtin", "gtin", unique=True, postgresql_where=text("gtin IS NOT NULL")),
        Index("uq_products_asin", "asin", unique=True, postgresql_where=text("asin IS NOT NULL")),
        Index(
            "uq_products_brand_model_variant",
            "brand",
            "model_number",
            "variant_key",
            unique=True,
            postgresql_where=text("model_number IS NOT NULL"),
        ),
        Index("ix_products_normalized_name", "normalized_name"),
        Index("ix_products_category_active", "category_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    brand: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL")
    )
    model_number: Mapped[str | None] = mapped_column(String(120))
    gtin: Mapped[str | None] = mapped_column(String(14))
    asin: Mapped[str | None] = mapped_column(String(10))
    # Normalised variant descriptor, e.g. "128gb|black". Empty string = no variants.
    variant_key: Mapped[str] = mapped_column(String(200), server_default="", nullable=False)
    specifications: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    image_url: Mapped[str | None] = mapped_column(String(2048))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)

    platforms: Mapped[list["ProductPlatform"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class ProductPlatform(TimestampMixin, Base):
    """One product's listing on one marketplace."""

    __tablename__ = "product_platforms"
    __table_args__ = (
        UniqueConstraint("platform", "external_product_id", name="uq_product_platforms_listing"),
        CheckConstraint(f"availability IN {AVAILABILITY_VALUES}", name="availability_valid"),
        CheckConstraint(
            "match_confidence IS NULL OR (match_confidence >= 0 AND match_confidence <= 100)",
            name="match_confidence_range",
        ),
        CheckConstraint("rating IS NULL OR (rating >= 0 AND rating <= 5)", name="rating_range"),
        CheckConstraint("review_count IS NULL OR review_count >= 0", name="reviews_non_negative"),
        CheckConstraint("current_price IS NULL OR current_price >= 0", name="current_price_non_negative"),
        Index("ix_product_platforms_product", "product_id"),
        Index("ix_product_platforms_price", "current_price"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    # Open-ended (not an enum) so new marketplaces need no migration.
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    external_product_id: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    # Only ever set from a provider/affiliate API response, never constructed.
    affiliate_url: Mapped[str | None] = mapped_column(String(2048))
    seller_name: Mapped[str | None] = mapped_column(String(200))
    availability: Mapped[str] = mapped_column(String(20), server_default="unknown", nullable=False)
    match_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    match_method: Mapped[str | None] = mapped_column(String(32))  # e.g. gtin, asin, model, title
    # As reported by the marketplace for this listing (unknown = NULL).
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    review_count: Mapped[int | None] = mapped_column(Integer)
    # Denormalised latest observation, refreshed on every collection (even when no history row
    # is written), so list/compare queries never scan price history. ``current_price`` is NULL
    # unless the listing is purchasable.
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    current_mrp: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    price_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)

    product: Mapped[Product] = relationship(back_populates="platforms")
