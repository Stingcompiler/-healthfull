"""The cashier module's e2e builders (``apps/payments/e2e_fixtures.py``)."""

from __future__ import annotations

import json
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command

from apps.billing.models import CreditNote
from apps.payments.models import CashHandover, Payment, Refund, Shift

pytestmark = pytest.mark.django_db


def run(name: str) -> dict[str, Any]:
    out = StringIO()
    call_command("e2e_fixture", name, params="{}", as_json=True, stdout=out)
    payload = json.loads(out.getvalue())
    assert payload["ok"] is True, payload
    result: dict[str, Any] = payload["result"]
    return result


def test_cashier_screens_builds_every_populated_screen_once(settings: Any) -> None:
    settings.DEBUG = True
    call_command("seed_e2e", stdout=StringIO())
    first = run("cashier_screens")
    closed = Shift.objects.get(pk=first["closed_shift"])
    assert closed.status == "closed"
    assert closed.variance is not None and closed.variance != 0
    opened = Shift.objects.get(pk=first["open_shift"])
    assert opened.status == "open"
    transfer = Payment.objects.get(pk=first["transfer"]["id"])
    assert (transfer.verification, transfer.shift_id) == ("pending", opened.pk)
    assert transfer.sender_name
    assert transfer.transfer_date is not None
    assert CashHandover.objects.filter(shift=opened, received_at__isnull=True).count() == 1
    assert CreditNote.objects.filter(status="draft").count() == 1
    assert Refund.objects.filter(status="requested").count() == 1

    again = run("cashier_screens")
    assert again == first
    assert CreditNote.objects.filter(status="draft").count() == 1
    assert CashHandover.objects.filter(shift=opened).count() == 1
