"""List pagination: ``?page=1&page_size=25&q=...`` -> ``{items, count, page, page_size}``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.db.models import Model, QuerySet
from ninja import Field, Schema

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


class PageParams(Schema):
    """Query parameters accepted by every list endpoint (use with ``Query[PageParams]``)."""

    page: int = Field(1, ge=1)
    page_size: int = Field(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    q: str | None = Field(None, max_length=200)


def paginate[M: Model](
    items: QuerySet[M] | Sequence[Any],
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """Slice ``items`` into one page.

    ``page`` and ``page_size`` are clamped to valid ranges (page >= 1,
    1 <= page_size <= MAX_PAGE_SIZE). A page past the end returns no items, not an error.
    Unordered querysets are ordered by primary key so pages are stable.
    """
    page = max(1, int(page))
    page_size = min(MAX_PAGE_SIZE, max(1, int(page_size)))
    offset = (page - 1) * page_size

    if isinstance(items, QuerySet):
        qs = items if items.ordered else items.order_by("pk")
        count = qs.count()
        rows: list[Any] = list(qs[offset : offset + page_size]) if offset < count else []
    else:
        count = len(items)
        rows = list(items[offset : offset + page_size])
    return {"items": rows, "count": count, "page": page, "page_size": page_size}
