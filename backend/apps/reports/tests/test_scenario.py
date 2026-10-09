"""The shared scenario builds through the services and keeps the books balanced."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.ledger import services as ledger
from apps.payments.tests import fin
from apps.reports.tests.scenario import Day

D = Decimal
pytestmark = pytest.mark.django_db


def test_scenario_books(day: Day) -> None:
    fin.assert_books_balance()
    assert ledger.account_balance("REVENUE") == D("22000.00")
    assert ledger.account_balance("DISCOUNT") == D("500.00")
    assert ledger.account_balance("AR_PAYER") == D("7000.00")
    assert ledger.account_balance("BANK_PENDING") == D("6000.00")
    assert ledger.account_balance("BANK") == D("3000.00")
    assert ledger.account_balance("CASH_OVER_SHORT") == D("100.00")
    assert day.shift.variance == D("-100.00")
    assert day.shift.expected_cash == D("6500.00")
    assert day.transfer_a.verification == "pending"
    assert day.transfer_b.verification == "confirmed"
    assert day.refund.status == "paid"
