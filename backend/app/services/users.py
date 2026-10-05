"""Profile, notification preferences and favourites."""
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationFailed
from app.engine.config import ScoringConfig
from app.models import Category, Product, User, UserFavoriteCategory, UserFavoriteProduct
from app.schemas.catalog import CategoryOut, ProductCard
from app.services.alerts import CHANNELS
from app.services.catalog_query import ProductFilter, list_categories, list_products

MAX_FAVORITES = 500


def validate_notification_preferences(prefs: dict) -> dict:
    """Keys must be known channels; values a bool, or (for telegram) an object with a chat_id."""
    unknown = sorted(set(prefs) - set(CHANNELS))
    if unknown:
        raise ValidationFailed("Unknown notification channels", [f"Unknown channel: {k}" for k in unknown])
    cleaned: dict = {}
    for key, value in prefs.items():
        if isinstance(value, bool):
            cleaned[key] = value
        elif key == "telegram" and isinstance(value, dict) and isinstance(value.get("chat_id"), (str, int)):
            cleaned[key] = {"chat_id": str(value["chat_id"])[:64]}
        else:
            raise ValidationFailed("Invalid notification preference", [f"{key} must be true/false"])
    return cleaned


async def update_profile(session: AsyncSession, user: User, name: str | None, prefs: dict | None) -> User:
    if name is not None:
        user.name = name.strip()
    if prefs is not None:
        user.notification_preferences = validate_notification_preferences(prefs)
    await session.commit()
    return user


async def add_favorite_product(session: AsyncSession, user_id: int, product_id: int) -> None:
    if await session.scalar(select(Product.id).where(Product.id == product_id, Product.is_active)) is None:
        raise NotFoundError("Product not found")
    count = len((await session.scalars(select(UserFavoriteProduct.product_id).where(UserFavoriteProduct.user_id == user_id))).all())
    if count >= MAX_FAVORITES:
        raise ValidationFailed(f"You can save at most {MAX_FAVORITES} favourite products")
    await session.execute(
        pg_insert(UserFavoriteProduct).values(user_id=user_id, product_id=product_id).on_conflict_do_nothing()
    )
    await session.commit()


async def remove_favorite_product(session: AsyncSession, user_id: int, product_id: int) -> None:
    await session.execute(delete(UserFavoriteProduct).where(
        UserFavoriteProduct.user_id == user_id, UserFavoriteProduct.product_id == product_id))
    await session.commit()


async def list_favorite_products(
    session: AsyncSession, user_id: int, config: ScoringConfig | None = None, now: datetime | None = None
) -> list[ProductCard]:
    ids = list((await session.scalars(
        select(UserFavoriteProduct.product_id).where(UserFavoriteProduct.user_id == user_id)
        .order_by(UserFavoriteProduct.created_at.desc())
    )).all())
    if not ids:
        return []
    cards, _ = await list_products(session, ProductFilter(ids=ids), "name", 1, len(ids), config, now, keep_id_order=True)
    return cards


async def add_favorite_category(session: AsyncSession, user_id: int, slug: str) -> None:
    category_id = await session.scalar(select(Category.id).where(Category.slug == slug.lower()))
    if category_id is None:
        raise NotFoundError("Category not found")
    await session.execute(
        pg_insert(UserFavoriteCategory).values(user_id=user_id, category_id=category_id).on_conflict_do_nothing()
    )
    await session.commit()


async def remove_favorite_category(session: AsyncSession, user_id: int, slug: str) -> None:
    category_id = await session.scalar(select(Category.id).where(Category.slug == slug.lower()))
    if category_id is not None:
        await session.execute(delete(UserFavoriteCategory).where(
            UserFavoriteCategory.user_id == user_id, UserFavoriteCategory.category_id == category_id))
        await session.commit()


async def favorite_category_slugs(session: AsyncSession, user_id: int) -> list[str]:
    return list((await session.scalars(
        select(Category.slug).join(UserFavoriteCategory, UserFavoriteCategory.category_id == Category.id)
        .where(UserFavoriteCategory.user_id == user_id).order_by(Category.slug)
    )).all())


async def list_favorite_categories(session: AsyncSession, user_id: int) -> list[CategoryOut]:
    slugs = set(await favorite_category_slugs(session, user_id))
    return [c for c in await list_categories(session) if c.slug in slugs]
