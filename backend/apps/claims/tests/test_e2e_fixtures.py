"""The claims module's e2e builders (``apps/claims/e2e_fixtures.py``)."""

from __future__ import annotations

import json
from decimal import Decimal
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command

from apps.catalog.models import Payer
from apps.claims import services as cs
from apps.claims.models import Claim, ClaimLine, PayerPayment
from apps.ledger import services as ledger

pytestmark = pytest.mark.django_db

D = Decimal


def run(name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    out = StringIO()
    call_command("e2e_fixture", name, params=json.dumps(params or {}), as_json=True, stdout=out)
    payload = json.loads(out.getvalue())
    assert payload["ok"] is True, payload
    result: dict[str, Any] = payload["result"]
    return result


def test_claims_case_reaches_each_stage_with_its_own_payer(settings: Any) -> None:
    settings.DEBUG = True
    call_command("seed_e2e", stdout=StringIO())
    accrued = run("claims_case")
    assert accrued["claim"] is None
    payer = Payer.objects.get(pk=accrued["payer"]["id"])
    # PRC-ECG 10,000 at 70%: the payer owes 7,000 on the first line.
    assert cs.accrued_lines(payer)[0].amount == D("7000.00")
    assert cs.payer_receivables(payer=payer)[payer.pk].receivable == ledger.account_balance(
        "AR_PAYER", payer=payer
    )

    answered = run(
        "claims_case",
        {
            "stage": "answered",
            "services": ["PRC-ECG", "LAB-CBC"],
            "outcomes": ["partial", "rejected"],
        },
    )
    assert answered["payer"]["id"] != payer.pk
    claim = answered["claim"]
    assert claim["status"] == "responded"
    assert [ln["status"] for ln in claim["lines"]] == ["partial", "rejected"]
    partial = ClaimLine.objects.get(pk=claim["lines"][0]["id"])
    assert (partial.accepted_amount, partial.rejected_amount) == (D("3500.00"), D("3500.00"))

    draft = run("claims_case", {"stage": "draft"})
    assert draft["claim"]["status"] == "draft"


def test_claims_screens_builds_every_populated_screen_once(settings: Any) -> None:
    settings.DEBUG = True
    call_command("seed_e2e", stdout=StringIO())
    first = run("claims_screens")
    assert Claim.objects.get(pk=first["draft_claim"]["id"]).status == "draft"
    answered = Claim.objects.get(pk=first["answered_claim"]["id"])
    assert answered.status == "responded"
    statuses = list(answered.lines.order_by("id").values_list("status", "resolution"))
    assert statuses == [
        ("accepted", "none"),
        ("partial", "none"),
        ("rejected", "rebilled"),
        ("rejected", "none"),
    ]
    payer = Payer.objects.get(pk=first["payer"]["id"])
    assert PayerPayment.objects.filter(payer=payer).count() == 2
    assert cs.payer_receivables(payer=payer)[payer.pk].accrued > 0
    again = run("claims_screens")
    assert again == first
    assert Claim.objects.filter(payer=payer).count() == 2
