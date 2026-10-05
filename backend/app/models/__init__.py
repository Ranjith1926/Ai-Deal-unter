"""Import every model so Base.metadata is complete (needed by Alembic)."""
from app.models.alerts import Notification, PriceAlert, PushSubscription
from app.models.auth import PasswordResetToken, RefreshToken
from app.models.catalog import Category, Product, ProductPlatform
from app.models.events import DealEvent
from app.models.ops import AppSetting, ProviderSyncLog, SaleEvent
from app.models.pricing import ProductOffer, ProductPrice, ProductScore
from app.models.user import User, UserFavoriteCategory, UserFavoriteProduct

__all__ = [
    "AppSetting",
    "Category",
    "DealEvent",
    "Notification",
    "PushSubscription",
    "PasswordResetToken",
    "PriceAlert",
    "Product",
    "ProductOffer",
    "ProductPlatform",
    "ProductPrice",
    "ProductScore",
    "ProviderSyncLog",
    "RefreshToken",
    "SaleEvent",
    "User",
    "UserFavoriteCategory",
    "UserFavoriteProduct",
]
