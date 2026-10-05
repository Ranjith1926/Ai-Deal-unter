"""Detected deal events (new deal, price drop, historical low, expiry, back in stock)."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

EVENT_TYPES = ("new_deal", "price_drop", "historical_low", "deal_expired", "back_in_stock")


class DealEvent(Base):
    __tablename__ = "deal_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('new_deal','price_drop','historical_low','deal_expired','back_in_stock')",
            name="event_type_valid",
        ),
        Index("ix_deal_events_detected", text("detected_at DESC")),
        Index("ix_deal_events_type_detected", "event_type", text("detected_at DESC")),
        Index("ix_deal_events_product_type_detected", "product_id", "event_type", text("detected_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    product_platform_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_platforms.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    previous_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    deal_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    detail: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
