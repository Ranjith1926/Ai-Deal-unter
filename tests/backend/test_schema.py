"""Schema tests that need no database.

The migration is rendered to SQL (offline mode) and compared with the DDL generated from the
SQLAlchemy models, so model/migration drift fails the build.
"""
import io
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

import app.models  # noqa: F401
from app.db.base import Base

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"

EXPECTED_TABLES = {
    "users", "categories", "products", "product_platforms", "product_prices", "product_offers",
    "product_scores", "price_alerts", "notifications", "push_subscriptions", "provider_sync_logs", "sale_events",
    "app_settings", "user_favorite_products", "user_favorite_categories", "deal_events",
    "refresh_tokens", "password_reset_tokens",
}


def _names(sql: str) -> dict[str, set[str]]:
    # Alembic's own bookkeeping table is not part of the models.
    sql = re.sub(r"CREATE TABLE alembic_version \(.*?\);", "", sql, flags=re.S)
    return {
        "tables": set(re.findall(r"CREATE TABLE (\w+)", sql)),
        "constraints": set(re.findall(r"CONSTRAINT (\w+)", sql)),
        "indexes": set(re.findall(r"CREATE (?:UNIQUE )?INDEX (\w+)", sql)),
    }


@pytest.fixture(scope="module")
def migration_sql() -> str:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.output_buffer = io.StringIO()
    command.upgrade(cfg, "head", sql=True)
    return cfg.output_buffer.getvalue()


@pytest.fixture(scope="module")
def model_sql() -> str:
    dialect = postgresql.dialect()
    parts = []
    for table in Base.metadata.sorted_tables:
        parts.append(str(CreateTable(table).compile(dialect=dialect)))
        parts.extend(str(CreateIndex(ix).compile(dialect=dialect)) for ix in table.indexes)
    return "\n".join(parts)


def test_all_expected_tables_exist():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_migration_matches_models(migration_sql, model_sql):
    migrated, modelled = _names(migration_sql), _names(model_sql)
    for kind in ("tables", "constraints", "indexes"):
        assert migrated[kind] == modelled[kind], (
            f"{kind} differ: only in migration={migrated[kind] - modelled[kind]}, "
            f"only in models={modelled[kind] - migrated[kind]}"
        )


def test_price_history_is_indexed_for_time_queries(migration_sql):
    assert "ix_product_prices_listing_captured" in migration_sql
    assert "captured_at DESC" in migration_sql


def test_variants_cannot_be_merged_by_model_number():
    ix = next(i for i in Base.metadata.tables["products"].indexes if i.name == "uq_products_brand_model_variant")
    assert [c.name for c in ix.columns] == ["brand", "model_number", "variant_key"]
    assert ix.unique


def test_every_foreign_key_has_ondelete():
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            assert fk.ondelete, f"{table.name}.{fk.parent.name} has no ON DELETE rule"
