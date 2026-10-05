"""Initial schema: users, catalog, price history, scores, alerts, notifications, ops.

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

NOW = sa.text("now()")
AVAILABILITY = "availability IN ('in_stock','out_of_stock','discontinued','unknown')"


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger, nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("external_auth_id", sa.String(255)),
        sa.Column("is_admin", sa.Boolean, server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column(
            "notification_preferences",
            postgresql.JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("external_auth_id", name=op.f("uq_users_external_auth_id")),
        sa.CheckConstraint(
            "password_hash IS NOT NULL OR external_auth_id IS NOT NULL",
            name=op.f("ck_users_has_credential"),
        ),
    )
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)

    op.create_table(
        "categories",
        sa.Column("id", sa.BigInteger, nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(140), nullable=False),
        sa.Column("parent_id", sa.BigInteger),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("slug", name=op.f("uq_categories_slug")),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["categories.id"],
            name=op.f("fk_categories_parent_id_categories"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(op.f("ix_categories_parent_id"), "categories", ["parent_id"])

    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger, nullable=False),
        sa.Column("brand", sa.String(120), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("normalized_name", sa.String(500), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("category_id", sa.BigInteger),
        sa.Column("model_number", sa.String(120)),
        sa.Column("gtin", sa.String(14)),
        sa.Column("asin", sa.String(10)),
        sa.Column("variant_key", sa.String(200), server_default="", nullable=False),
        sa.Column(
            "specifications", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("image_url", sa.String(2048)),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_products_category_id_categories"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "uq_products_gtin", "products", ["gtin"], unique=True, postgresql_where=sa.text("gtin IS NOT NULL")
    )
    op.create_index(
        "uq_products_asin", "products", ["asin"], unique=True, postgresql_where=sa.text("asin IS NOT NULL")
    )
    op.create_index(
        "uq_products_brand_model_variant",
        "products",
        ["brand", "model_number", "variant_key"],
        unique=True,
        postgresql_where=sa.text("model_number IS NOT NULL"),
    )
    op.create_index("ix_products_normalized_name", "products", ["normalized_name"])
    op.create_index("ix_products_category_active", "products", ["category_id", "is_active"])

    op.create_table(
        "product_platforms",
        sa.Column("id", sa.BigInteger, nullable=False),
        sa.Column("product_id", sa.BigInteger, nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("external_product_id", sa.String(128), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("affiliate_url", sa.String(2048)),
        sa.Column("seller_name", sa.String(200)),
        sa.Column("availability", sa.String(20), server_default="unknown", nullable=False),
        sa.Column("match_confidence", sa.Numeric(5, 2)),
        sa.Column("match_method", sa.String(32)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_platforms")),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_platforms_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("platform", "external_product_id", name="uq_product_platforms_listing"),
        sa.CheckConstraint(AVAILABILITY, name=op.f("ck_product_platforms_availability_valid")),
        sa.CheckConstraint(
            "match_confidence IS NULL OR (match_confidence >= 0 AND match_confidence <= 100)",
            name=op.f("ck_product_platforms_match_confidence_range"),
        ),
    )
    op.create_index("ix_product_platforms_product", "product_platforms", ["product_id"])

    op.create_table(
        "product_prices",
        sa.Column("id", sa.BigInteger, nullable=False),
        sa.Column("product_platform_id", sa.BigInteger, nullable=False),
        sa.Column("price", sa.Numeric(12, 2)),
        sa.Column("mrp", sa.Numeric(12, 2)),
        sa.Column("currency", sa.String(3), server_default="INR", nullable=False),
        sa.Column("availability", sa.String(20), server_default="unknown", nullable=False),
        sa.Column("seller_name", sa.String(200)),
        sa.Column("data_quality", sa.String(12), server_default="verified", nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_prices")),
        sa.ForeignKeyConstraint(
            ["product_platform_id"],
            ["product_platforms.id"],
            name=op.f("fk_product_prices_product_platform_id_product_platforms"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("price IS NULL OR price >= 0", name=op.f("ck_product_prices_price_non_negative")),
        sa.CheckConstraint("mrp IS NULL OR mrp >= 0", name=op.f("ck_product_prices_mrp_non_negative")),
        sa.CheckConstraint(AVAILABILITY, name=op.f("ck_product_prices_availability_valid")),
        sa.CheckConstraint(
            "data_quality IN ('verified','estimated')", name=op.f("ck_product_prices_data_quality_valid")
        ),
        sa.CheckConstraint(
            "price IS NOT NULL OR availability <> 'in_stock'",
            name=op.f("ck_product_prices_in_stock_has_price"),
        ),
    )
    op.create_index(
        "ix_product_prices_listing_captured",
        "product_prices",
        ["product_platform_id", sa.text("captured_at DESC")],
    )
    op.create_index("ix_product_prices_captured", "product_prices", ["captured_at"])

    op.create_table(
        "product_offers",
        sa.Column("id", sa.BigInteger, nullable=False),
        sa.Column("product_platform_id", sa.BigInteger, nullable=False),
        sa.Column("offer_type", sa.String(20), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("discount_amount", sa.Numeric(12, 2)),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_offers")),
        sa.ForeignKeyConstraint(
            ["product_platform_id"],
            ["product_platforms.id"],
            name=op.f("fk_product_offers_product_platform_id_product_platforms"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "offer_type IN ('bank','exchange','coupon','cashback','no_cost_emi','other')",
            name=op.f("ck_product_offers_offer_type_valid"),
        ),
        sa.CheckConstraint(
            "discount_amount IS NULL OR discount_amount >= 0",
            name=op.f("ck_product_offers_discount_non_negative"),
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
            name=op.f("ck_product_offers_valid_range"),
        ),
    )
    op.create_index(
        "ix_product_offers_listing_captured",
        "product_offers",
        ["product_platform_id", sa.text("captured_at DESC")],
    )

    op.create_table(
        "product_scores",
        sa.Column("id", sa.BigInteger, nullable=False),
        sa.Column("product_id", sa.BigInteger, nullable=False),
        sa.Column("deal_score", sa.Numeric(5, 2)),
        sa.Column("value_score", sa.Numeric(5, 2)),
        sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column(
            "score_reason", postgresql.JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_scores")),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_scores_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "deal_score IS NULL OR (deal_score BETWEEN 0 AND 100)",
            name=op.f("ck_product_scores_deal_score_range"),
        ),
        sa.CheckConstraint(
            "value_score IS NULL OR (value_score BETWEEN 0 AND 100)",
            name=op.f("ck_product_scores_value_score_range"),
        ),
    )
    op.create_index(
        "ix_product_scores_product_calculated",
        "product_scores",
        ["product_id", sa.text("calculated_at DESC")],
    )
    op.create_index(
        "ix_product_scores_calculated_deal",
        "product_scores",
        [sa.text("calculated_at DESC"), sa.text("deal_score DESC")],
    )

    op.create_table(
        "price_alerts",
        sa.Column("id", sa.BigInteger, nullable=False),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("product_id", sa.BigInteger, nullable=False),
        sa.Column("target_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("platform", sa.String(32)),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_alerts")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_price_alerts_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_price_alerts_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("target_price > 0", name=op.f("ck_price_alerts_target_positive")),
    )
    op.create_index("ix_price_alerts_user", "price_alerts", ["user_id"])
    op.create_index(
        "ix_price_alerts_active_product",
        "price_alerts",
        ["product_id"],
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger, nullable=False),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("status", sa.String(12), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_notifications_user_id_users"), ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "type IN ('email','push','telegram','in_app')", name=op.f("ck_notifications_type_valid")
        ),
        sa.CheckConstraint(
            "status IN ('pending','sent','failed','read')", name=op.f("ck_notifications_status_valid")
        ),
    )
    op.create_index(
        "ix_notifications_user_created", "notifications", ["user_id", sa.text("created_at DESC")]
    )
    op.create_index(
        "ix_notifications_pending",
        "notifications",
        ["created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "user_favorite_products",
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("product_id", sa.BigInteger, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("user_id", "product_id", name=op.f("pk_user_favorite_products")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_favorite_products_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_user_favorite_products_product_id_products"),
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "user_favorite_categories",
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("category_id", sa.BigInteger, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("user_id", "category_id", name=op.f("pk_user_favorite_categories")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_favorite_categories_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_user_favorite_categories_category_id_categories"),
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "provider_sync_logs",
        sa.Column("id", sa.BigInteger, nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("job_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("records_processed", sa.Integer, server_default="0", nullable=False),
        sa.Column("error_message", sa.Text),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_sync_logs")),
        sa.CheckConstraint(
            "status IN ('running','success','failed','partial')",
            name=op.f("ck_provider_sync_logs_status_valid"),
        ),
        sa.CheckConstraint(
            "records_processed >= 0", name=op.f("ck_provider_sync_logs_records_non_negative")
        ),
    )
    op.create_index(
        "ix_provider_sync_logs_provider_started",
        "provider_sync_logs",
        ["provider", sa.text("started_at DESC")],
    )

    op.create_table(
        "sale_events",
        sa.Column("id", sa.BigInteger, nullable=False),
        sa.Column("event_name", sa.String(200), nullable=False),
        sa.Column("platform", sa.String(32)),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sale_events")),
        sa.CheckConstraint("end_date >= start_date", name=op.f("ck_sale_events_date_range_valid")),
    )
    op.create_index("ix_sale_events_dates", "sale_events", ["start_date", "end_date"])

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", postgresql.JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_settings")),
    )


def downgrade() -> None:
    # Reverse dependency order. Dropping a table drops its indexes.
    for table in (
        "app_settings",
        "sale_events",
        "provider_sync_logs",
        "user_favorite_categories",
        "user_favorite_products",
        "notifications",
        "price_alerts",
        "product_scores",
        "product_offers",
        "product_prices",
        "product_platforms",
        "products",
        "categories",
        "users",
    ):
        op.drop_table(table)
