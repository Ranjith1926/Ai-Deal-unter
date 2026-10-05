"""Shared response types: the standard envelope, pagination metadata and money serialisation."""
from decimal import Decimal
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, Field, PlainSerializer

# Prices are Decimal internally and plain JSON numbers on the wire.
Money = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]

T = TypeVar("T")


class Meta(BaseModel):
    page: int
    page_size: int
    total: int
    pages: int


class Envelope(BaseModel, Generic[T]):
    success: bool = True
    data: T | None = None
    message: str | None = None
    errors: list[str] = Field(default_factory=list)
    meta: Meta | None = None


def ok(data: Any = None, message: str | None = None, meta: Meta | None = None) -> dict:
    out: dict[str, Any] = {"success": True, "data": data, "message": message, "errors": []}
    if meta is not None:
        out["meta"] = meta
    return out


def page_meta(page: int, page_size: int, total: int) -> Meta:
    return Meta(page=page, page_size=page_size, total=total, pages=max(1, -(-total // page_size)))
