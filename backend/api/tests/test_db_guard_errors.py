"""Database guard errors reach the user as specific, translated 409 codes (F05).

The guards (triggers, ARCHITECTURE 4.9) raise ``'<CODE>: <detail>'``. The API answers the
code from ``DB_GUARD_CODES`` and never the SQL text, which names tables, ids and values.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from django.db import connection

from api.errors import DB_GUARD_CODES, db_guard_code
from apps.core.tests import builders as b
from conftest import ApiClient

pytestmark = [pytest.mark.django_db, pytest.mark.urls("api.tests.urls")]

_LEAKS = ("pharmacy_", "orders_", "payments_", "billing_", "SELECT", "INSERT", "line 42", "%")


def _raise(api_client: ApiClient, message: str) -> Any:
    return api_client.post("/test-api/db-raise", {"name": message, "count": 0})


def _trigger_codes() -> set[str]:
    """Every ``RAISE EXCEPTION '<CODE>:`` in the trigger functions of the migrated schema."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT prosrc FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
            " WHERE n.nspname = 'public' AND p.prorettype = 'trigger'::regtype"
        )
        sources = [row[0] for row in cursor.fetchall()]
    found: set[str] = set()
    for src in sources:
        found.update(re.findall(r"RAISE\s+EXCEPTION\s+'([A-Za-z][A-Za-z0-9_]*):", src))
    return found


def test_every_guard_code_in_the_schema_is_mapped_and_nothing_stale() -> None:
    in_schema = _trigger_codes()
    assert len(in_schema) > 40, in_schema  # the scan itself works
    assert in_schema - set(DB_GUARD_CODES) == set(), "map these in api/errors.py DB_GUARD_CODES"
    assert set(DB_GUARD_CODES) - in_schema == set(), "no trigger raises these any more"


@pytest.mark.parametrize(("guard", "code"), sorted(DB_GUARD_CODES.items()))
def test_guard_answers_409_with_its_code_and_no_sql(
    api_client: ApiClient, guard: str, code: str
) -> None:
    detail = (
        "Cannot update rows from payments_payment table"
        if guard == "pgtrigger"
        else "service line 42 in orders_serviceline is % locked"
    )
    response = _raise(api_client, f"{guard}: {detail}")
    assert response.status_code == 409, response.content
    body = response.json()
    assert body["code"] == code
    assert body["details"] == {}
    for leak in _LEAKS:
        assert leak not in body["message"]


def test_codes_with_placeholder_texts_answer_their_guard_sibling() -> None:
    # The service sends `remaining` / `effective_from`; the trigger cannot.
    assert DB_GUARD_CODES["DISPENSE_EXCEEDS_LINE"] == "DISPENSE_EXCEEDS_LINE_GUARD"
    assert DB_GUARD_CODES["PRICE_VERSION_LOCKED"] == "PRICE_VERSION_LOCKED_GUARD"


def test_unknown_database_error_stays_internal_and_hides_the_text(api_client: ApiClient) -> None:
    response = _raise(api_client, "SOMETHING_NEW: secret orders_serviceline 42")
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert "orders_serviceline" not in body["message"]
    response = _raise(api_client, "no code here at all")
    assert response.json()["code"] == "INTERNAL_ERROR"


def test_db_guard_code_reads_only_the_leading_code() -> None:
    assert db_guard_code(Exception("LINE_TERMINAL: line 5 is performed")) == "LINE_TERMINAL"
    assert db_guard_code(Exception("context LINE_TERMINAL: x")) is None
    assert db_guard_code(Exception("NOT_A_GUARD: x")) is None


def test_a_real_guard_through_the_orm_maps_to_its_code() -> None:
    """A real trigger (append-only stock ledger) raises a text the mapping recognises."""
    from django.db import DatabaseError, transaction

    from apps.pharmacy.models import StockMove

    batch, store = b.batch(), b.store()
    move = b.stock_move(batch, store, "10")
    with pytest.raises(DatabaseError) as exc, transaction.atomic():
        StockMove.objects.filter(pk=move.pk).update(note="x")
    assert db_guard_code(exc.value) == "APPEND_ONLY"
