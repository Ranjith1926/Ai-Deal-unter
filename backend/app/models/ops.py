"""Operational tables: provider sync logs, sale events and runtime configuration."""
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProviderSyncLog(Base):
    __tablename__ = "provider_sync_logs"
    __table_args__ = (
        CheckConstraint("status IN ('running','success','failed','partial')", name="status_valid"),
        CheckConstraint("records_processed >= 0", name="records_non_negative"),
        Index("ix_provider_sync_logs_provider_started", "provider", text("started_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    job_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    records_processed: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SaleEvent(Base):
    """Configurable sale events (Big Billion Days, Great Indian Festival, ...). No hard-coded dates."""

    __tablename__ = "sale_events"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="date_range_valid"),
        Index("ix_sale_events_dates", "start_date", "end_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_name: Mapped[str] = mapped_column(String(200), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(32))  # NULL = all platforms
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)


class AppSetting(Base):
    """Key/value runtime config (scoring weights, deal thresholds), editable from the admin UI."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
