"""Schemas shared by every router."""

from __future__ import annotations

from typing import Any

from ninja import Field, Schema


class ErrorOut(Schema):
    """Body of every non-2xx response."""

    code: str = Field(..., description="Stable machine-readable error code")
    message: str = Field(..., description="Developer-facing message (UI translates `code`)")
    details: dict[str, Any] = Field(..., description="Extra context; may be empty")


class PingOut(Schema):
    """Body of ``GET /api/<module>/ping``: proves the module router is mounted."""

    module: str = Field(..., description="Name of the module router that answered")


class Page[T](Schema):
    """One page of a list endpoint: ``?page=1&page_size=25&q=...``."""

    items: list[T]
    count: int = Field(..., ge=0, description="Total number of matching items")
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)


#: Standard error responses to merge into an operation's ``response=`` mapping.
ERROR_RESPONSES: dict[int, type[ErrorOut]] = {
    401: ErrorOut,
    403: ErrorOut,
    409: ErrorOut,
    422: ErrorOut,
}
