"""Report figures equal the ledger (ARCHITECTURE 4.7): the reports read documents, the
ledger is posted by the services, and both must tell the same story."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db.models import Sum
from django.utils import timezone

from apps.ledger import services as ledger
from apps.ledger.models import JournalLine
from apps.payments import services as pay
from apps.reports import queries
from apps.reports.kit import Filters, as_money, resolve_filters
from apps.reports.tests.scenario import Day
from domain.money import ZERO

D = Decimal
pytestmark = pytest.mark.django_db


def _today() -> Filters:
    today = timezone.localdate()
    return resolve_filters(date_from=today, date_to=today)


def _posted(account: str, source: str, side: str) -> Decimal:
    total = JournalLine.objects.filter(account__code=account, entry__source_type=source).aggregate(
        s=Sum(side)
    )["s"]
    return total or ZERO


def _check_revenue_against_ledger() -> None:
    r = queries.revenue(_today())
    assert r.metric("net_revenue") == ledger.account_balance("REVENUE") - ledger.account_balance(
        "DISCOUNT"
    )
    assert r.metric("gross") == _posted("REVENUE", "invoice", "credit")
    assert r.metric("credited") == _posted("REVENUE", "credit_note", "debit")
    assert r.metric("discount") == _posted("DISCOUNT", "invoice", "debit")
    # No claim activity: the payer share billed is exactly what payers owe (invariant 7).
    assert r.metric("payer_share") == ledger.account_balance("AR_PAYER")
    assert r.metric("pending_transfers") == ledger.account_balance("BANK_PENDING")
    assert r.metric("bank_confirmed") == ledger.account_balance("BANK")
    assert r.metric("cash") == _posted("CASH", "payment", "debit")


def test_revenue_and_collections_match_the_ledger(day: Day) -> None:
    _check_revenue_against_ledger()


def test_shift_variances_match_cash_over_short(day: Day) -> None:
    r = queries.shift_variances(_today())
    # A shortage is a debit to CASH_OVER_SHORT; the report's variance is counted - expected.
    assert r.metric("net_variance") == -ledger.account_balance("CASH_OVER_SHORT")
    assert r.section("shifts").totals == {
        "expected": D("6500.00"),
        "counted": D("6400.00"),
        "variance": D("-100.00"),
    }


def test_pending_transfers_match_bank_pending(day: Day) -> None:
    r = queries.pending_transfers(_today())
    held = as_money(r.metric("pending_total")) + as_money(r.metric("cheques_pending"))
    assert held == ledger.account_balance("BANK_PENDING")
    dashboard = {m.key: m.value for m in queries.dashboard().metrics}
    assert dashboard["pending_transfers"] == ledger.account_balance("BANK_PENDING")


def test_adjustments_match_the_ledger(day: Day) -> None:
    r = queries.adjustments(_today())
    assert r.metric("discounts") == _posted("DISCOUNT", "invoice", "debit")
    assert r.metric("credit_notes") == _posted("REVENUE", "credit_note", "debit")
    assert r.metric("refunds") == _posted("CASH", "refund", "credit")


def test_payer_receivables_match_ar_payer(day: Day) -> None:
    r = queries.payer_receivables(_today())
    assert r.metric("receivable") == ledger.account_balance("AR_PAYER")


def test_a_rejected_transfer_leaves_collections_and_the_ledger_in_step(day: Day) -> None:
    """The shift that took the transfer is closed: the rejection books a reversal in the
    supervisor's open shift. The rejected money is never collected, nothing stays pending,
    and the reversal row is not counted twice."""
    pay.open_shift(day.supervisor, D("0.00"))
    pay.reject_transfer(day.transfer_a, actor=day.supervisor, reason="NOT_RECEIVED")
    r = queries.revenue(_today())
    assert r.metric("pending_transfers") == D("0.00")
    assert r.metric("rejected_transfers") == D("6000.00")
    assert r.metric("collected") == D("13500.00")
    _check_revenue_against_ledger()
    assert queries.pending_transfers(_today()).metric("pending_count") == 0
