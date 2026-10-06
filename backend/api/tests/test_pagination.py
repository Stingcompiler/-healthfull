from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from api.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, paginate
from apps.core.models import Department


@given(
    st.integers(min_value=0, max_value=300),
    st.integers(min_value=-5, max_value=50),
    st.integers(min_value=-5, max_value=500),
)
def test_paginate_list_properties(total: int, page: int, page_size: int) -> None:
    items = list(range(total))
    result = paginate(items, page, page_size)
    assert result["count"] == total
    assert result["page"] == max(1, page)
    assert 1 <= result["page_size"] <= MAX_PAGE_SIZE
    start = (result["page"] - 1) * result["page_size"]
    assert result["items"] == items[start : start + result["page_size"]]


def test_paginate_defaults() -> None:
    result = paginate(list(range(60)))
    assert result["page"] == 1
    assert result["page_size"] == DEFAULT_PAGE_SIZE
    assert result["items"] == list(range(25))


@given(st.integers(min_value=1, max_value=10))
def test_pages_cover_every_item_exactly_once(page_size: int) -> None:
    items = list(range(37))
    seen: list[int] = []
    page = 1
    while True:
        chunk = paginate(items, page, page_size)["items"]
        if not chunk:
            break
        seen.extend(chunk)
        page += 1
    assert seen == items


@pytest.mark.django_db
def test_paginate_queryset_orders_unordered_querysets_by_pk() -> None:
    created = [Department.objects.create(code=f"Z{i}", name_ar="x", name_en="x") for i in range(5)]
    qs = Department.objects.filter(code__startswith="Z").order_by()
    assert not qs.ordered
    result = paginate(qs, 1, 3)
    assert result["count"] == 5
    assert [d.pk for d in result["items"]] == [d.pk for d in created[:3]]
    assert [d.pk for d in paginate(qs, 2, 3)["items"]] == [d.pk for d in created[3:]]


@pytest.mark.django_db
def test_paginate_queryset_past_the_end_is_empty(django_assert_num_queries: Any) -> None:
    Department.objects.create(code="ONLY", name_ar="x", name_en="x")
    qs = Department.objects.filter(code="ONLY").order_by("code")
    with django_assert_num_queries(1):  # only the COUNT; no pointless SELECT
        result = paginate(qs, 5, 10)
    assert result == {"items": [], "count": 1, "page": 5, "page_size": 10}


@pytest.mark.django_db
def test_paginate_respects_existing_ordering() -> None:
    for code in ("B", "A", "C"):
        Department.objects.create(code=f"Q{code}", name_ar="x", name_en="x")
    qs = Department.objects.filter(code__startswith="Q").order_by("-code")
    assert [d.code for d in paginate(qs)["items"]] == ["QC", "QB", "QA"]
