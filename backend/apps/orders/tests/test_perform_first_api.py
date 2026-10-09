"""``/api/orders/perform-first`` contract (FEATURES 4.4, invariant 1).

Happy path, permission denied and domain errors; the authorization rules themselves are
tested in ``test_services.py`` and ``domain/tests``.
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.orders.models import ServiceLine
from apps.payments.tests import api_kit as kit
from apps.payments.tests.api_kit import Desk, error, ok

pytestmark = pytest.mark.django_db

URL = "/api/orders/perform-first"


@pytest.fixture
def d(make_user: Any) -> Desk:
    return kit.desk(make_user)


def test_supervisor_authorizes_unpaid_lines_and_revokes(d: Desk) -> None:
    iv = kit.insured_visit(d.doctor.user)
    body = ok(d.sup.api.get(f"{URL}/visits/{iv.visit.pk}"))
    assert [ln["id"] for ln in body["lines"]] == [iv.insured.pk, iv.cash_line.pk]
    assert all(ln["authorizable"] for ln in body["lines"])
    # No prices on this screen.
    assert "gross" not in str(body)
    assert "price" not in str(body)

    error(
        d.sup.api.post(
            URL, {"line_ids": [iv.insured.pk], "kind": "insurance_approval", "reason": "EMERGENCY"}
        ),
        409,
        "APPROVAL_REFERENCE_REQUIRED",
    )
    auth = ok(
        d.sup.api.post(
            URL,
            {
                "line_ids": [iv.insured.pk],
                "kind": "emergency",
                "reason": "EMERGENCY",
                "note": "bleeding",
            },
        ),
        201,
    )
    assert auth["authorized_by"]["username"] == "sup"
    assert auth["reason"]["code"] == "EMERGENCY"
    assert [ln["id"] for ln in auth["lines"]] == [iv.insured.pk]
    assert auth["lines"][0]["authorized"] is True
    assert ServiceLine.objects.get(pk=iv.insured.pk).authorization_id == auth["id"]
    error(
        d.sup.api.post(URL, {"line_ids": [iv.insured.pk], "reason": "EMERGENCY"}),
        409,
        "LINE_ALREADY_AUTHORIZED",
    )

    listed = ok(d.manager.api.get(f"{URL}?active=true"))
    assert [a["id"] for a in listed["items"]] == [auth["id"]]

    error(d.sup.api.post(f"{URL}/{auth['id']}/revoke", {"note": ""}), 422, "VALIDATION_ERROR")
    revoked = ok(d.sup.api.post(f"{URL}/{auth['id']}/revoke", {"note": "paid after all"}))
    assert revoked["revoked_by"]["username"] == "sup"
    assert ok(d.manager.api.get(f"{URL}?active=true"))["items"] == []


def test_cashiers_and_doctors_cannot_authorize(d: Desk) -> None:
    iv = kit.insured_visit(d.doctor.user)
    payload = {"line_ids": [iv.insured.pk], "reason": "EMERGENCY"}
    for actor in (d.cashier, d.doctor):
        error(actor.api.post(URL, payload), 403, "PERMISSION_DENIED")
        error(actor.api.get(f"{URL}/visits/{iv.visit.pk}"), 403, "PERMISSION_DENIED")


def test_lines_of_two_visits_are_refused(d: Desk) -> None:
    a = kit.insured_visit(d.doctor.user)
    b = kit.insured_visit(d.doctor.user)
    error(
        d.sup.api.post(URL, {"line_ids": [a.insured.pk, b.insured.pk], "reason": "EMERGENCY"}),
        409,
        "LINES_NOT_ONE_VISIT",
    )
    error(d.sup.api.post(URL, {"line_ids": [999999], "reason": "EMERGENCY"}), 404, "NOT_FOUND")


def test_the_requester_of_the_exception_is_recorded(d: Desk) -> None:
    """FEATURES 4.4 "who": the doctor who asked is kept apart from the authorizer."""
    iv = kit.insured_visit(d.doctor.user)
    people = ok(d.sup.api.get(f"{URL}/requesters?q=doc"))
    assert [u["username"] for u in people] == ["doc"]
    error(d.cashier.api.get(f"{URL}/requesters"), 403, "PERMISSION_DENIED")
    error(
        d.sup.api.post(
            URL, {"line_ids": [iv.insured.pk], "reason": "EMERGENCY", "requested_by_id": 999999}
        ),
        404,
        "NOT_FOUND",
    )
    auth = ok(
        d.sup.api.post(
            URL,
            {
                "line_ids": [iv.insured.pk],
                "kind": "emergency",
                "reason": "EMERGENCY",
                "requested_by_id": d.doctor.user.pk,
            },
        ),
        201,
    )
    assert auth["requested_by"]["username"] == "doc"
    assert auth["authorized_by"]["username"] == "sup"
