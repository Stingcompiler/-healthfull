"""``manage.py integrity_check``: ledger balance, document positions, stock and orphan
allocations on real data built through the services, and each check catching the damage it
exists for (written past the database guards on purpose)."""

from __future__ import annotations

import contextlib
import json
from io import StringIO
from typing import Any

import pytest
from django.core.management import CommandError, call_command
from django.db import connection

from apps.billing.models import DocumentStatus, Invoice
from apps.ledger.models import Account, JournalEntry
from apps.ops import integrity
from apps.payments.models import Allocation, Shift, ShiftStatus
from apps.pharmacy.models import StockBalance

pytestmark = pytest.mark.django_db


def fixture(name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    out = StringIO()
    call_command("e2e_fixture", name, params=json.dumps(params or {}), as_json=True, stdout=out)
    payload = json.loads(out.getvalue())
    assert payload["ok"] is True, payload
    result: dict[str, Any] = payload["result"]
    return result


@pytest.fixture
def activity(settings: Any) -> None:
    """A center with money, claims and stock: the seed, a day of cashier work (cash, discount,
    pending transfer), closed and open shifts with a handover, a credit note draft and a
    refund request, and a payer claim answered with a partial and a rejected line."""
    settings.DEBUG = True
    call_command("seed_e2e", stdout=StringIO())
    fixture("reports_day")
    fixture("cashier_screens")
    fixture(
        "claims_case",
        {
            "stage": "answered",
            "services": ["PRC-ECG", "LAB-CBC"],
            "outcomes": ["partial", "rejected"],
        },
    )


def check(*names: str) -> dict[str, Any]:
    out = StringIO()
    with contextlib.suppress(CommandError):
        call_command("integrity_check", "--json", *[f"--check={n}" for n in names], stdout=out)
    data: dict[str, Any] = json.loads(out.getvalue())
    return data


def damage(sql: str, params: list[Any]) -> None:
    """Write past the triggers (a superuser in a test transaction; production's app role can
    never do this): ordinary and deferred triggers are off for the rest of the transaction."""
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = replica")
        cursor.execute(sql, params)


def entry(source_type: str, source_id: int, lines: list[dict[str, Any]]) -> None:
    accounts = {a.code: a.pk for a in Account.objects.all()}
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = replica")
        cursor.execute(
            "INSERT INTO ledger_journalentry (source_type, source_id, entry_date, memo, posted_at)"
            " VALUES (%s, %s, current_date, 'test damage', now()) RETURNING id",
            [source_type, source_id],
        )
        row = cursor.fetchone()
        assert row is not None
        for ln in lines:
            cursor.execute(
                "INSERT INTO ledger_journalline (entry_id, account_id, debit, credit, invoice_id,"
                " patient_id, shift_id, payer_id, service_kind, memo)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '', '')",
                [
                    row[0],
                    accounts[ln["account"]],
                    ln.get("debit", 0),
                    ln.get("credit", 0),
                    ln.get("invoice"),
                    ln.get("patient"),
                    ln.get("shift"),
                    ln.get("payer"),
                ],
            )


def test_an_empty_database_passes() -> None:
    out = StringIO()
    call_command("integrity_check", stdout=out)
    assert "all checks passed" in out.getvalue()
    assert integrity.run().ok


def test_real_activity_passes_every_check(activity: None) -> None:
    data = check()
    assert data["ok"] is True, json.dumps(data, indent=2)
    assert set(data["checks"]) == set(integrity.CHECKS)
    checks = data["checks"]
    assert checks["invoice_positions"]["checked"] >= 3
    assert checks["shift_cash"]["checked"] >= 2
    assert checks["payer_receivables"]["checked"] >= 1
    assert checks["stock"]["checked"] >= 1
    assert checks["allocations"]["checked"] >= 1
    assert checks["ledger_balanced"]["checked"] >= 5


def test_an_unbalanced_entry_fails_the_ledger_check(activity: None) -> None:
    entry("payment", 999_999, [{"account": "CASH_SAFE", "debit": "10.00"}])
    data = check("ledger_balanced")
    assert data["ok"] is False
    examples = data["checks"]["ledger_balanced"]["examples"]
    assert any("trial balance" in e for e in examples)
    assert any("1 line(s)" in e for e in examples)


def test_an_ar_patient_posting_without_documents_fails_the_positions(activity: None) -> None:
    invoice = Invoice.objects.filter(status=DocumentStatus.APPROVED).first()
    assert invoice is not None
    entry(
        "invoice",
        invoice.pk,
        [
            {
                "account": "AR_PATIENT",
                "debit": "25.00",
                "invoice": invoice.pk,
                "patient": invoice.patient_id,
            },
            {"account": "REVENUE", "credit": "25.00"},
        ],
    )
    data = check("invoice_positions", "ledger_balanced")
    assert data["checks"]["ledger_balanced"]["ok"] is True  # balanced, but wrong
    problems = data["checks"]["invoice_positions"]
    assert problems["problems"] == 1
    assert f"invoice {invoice.pk}" in problems["examples"][0]


def test_cash_on_a_closed_shift_fails_the_shift_check(activity: None) -> None:
    shift = Shift.objects.filter(status=ShiftStatus.CLOSED).first()
    assert shift is not None
    entry(
        "shift_close",
        shift.pk,
        [
            {"account": "CASH", "debit": "5.00", "shift": shift.pk},
            {"account": "CASH_SAFE", "credit": "5.00"},
        ],
    )
    data = check("shift_cash")
    assert data["ok"] is False
    assert f"shift {shift.pk}: expected cash 0" in data["checks"]["shift_cash"]["examples"][0]


def test_a_payer_posting_without_claims_documents_fails(activity: None) -> None:
    from apps.catalog.models import Payer

    payer = Payer.objects.order_by("id").first()
    assert payer is not None
    entry(
        "claim_rebill",
        1,
        [
            {"account": "AR_PAYER", "debit": "7.00", "payer": payer.pk},
            {"account": "REVENUE", "credit": "7.00"},
        ],
    )
    data = check("payer_receivables")
    assert data["ok"] is False
    assert f"payer {payer.pk}" in data["checks"]["payer_receivables"]["examples"][0]


def test_a_stock_balance_that_disagrees_with_its_moves_fails(activity: None) -> None:
    balance = StockBalance.objects.filter(qty_base__gt=0).first()
    assert balance is not None
    damage("UPDATE pharmacy_stockbalance SET qty_base = qty_base + 3 WHERE id = %s", [balance.pk])
    data = check("stock")
    assert data["ok"] is False
    assert (
        f"batch {balance.batch_id} store {balance.store_id}"
        in (data["checks"]["stock"]["examples"][0])
    )


def test_negative_stock_is_reported(activity: None) -> None:
    balance = StockBalance.objects.filter(qty_base__gt=0).first()
    assert balance is not None
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")  # fire the fixtures' deferred checks
        cursor.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'pharmacy_stockbalance'::regclass"
            " AND contype = 'c'"
        )
        for (name,) in cursor.fetchall():
            cursor.execute(f'ALTER TABLE pharmacy_stockbalance DROP CONSTRAINT "{name}"')
    damage("UPDATE pharmacy_stockbalance SET qty_base = -1 WHERE id = %s", [balance.pk])
    examples = check("stock")["checks"]["stock"]["examples"]
    assert any("negative stock -1" in e for e in examples)


def test_orphan_allocation_entries_and_unposted_allocations_fail(activity: None) -> None:
    allocation = Allocation.objects.order_by("id").first()
    assert allocation is not None
    # An ALLOCATION entry for an allocation that does not exist, and a second entry for one
    # that does.
    for source_id in (987_654, allocation.pk):
        entry(
            "allocation",
            source_id,
            [
                {
                    "account": "PATIENT_CREDIT",
                    "debit": "1.00",
                    "patient": allocation.payment.patient_id,
                },
                {
                    "account": "PATIENT_CREDIT",
                    "credit": "1.00",
                    "patient": allocation.payment.patient_id,
                },
            ],
        )
    data = check("allocations")
    examples = data["checks"]["allocations"]["examples"]
    assert data["ok"] is False
    assert any("allocation 987654, which does not exist" in e for e in examples)
    assert any(f"allocation {allocation.pk}: 2 ledger entries" in e for e in examples)


def test_text_output_lists_problems_and_fails(activity: None) -> None:
    entry("payment", 999_998, [{"account": "CASH_SAFE", "credit": "10.00"}])
    out = StringIO()
    with pytest.raises(CommandError, match="ledger_balanced"):
        call_command("integrity_check", stdout=out)
    text = out.getvalue()
    assert "ledger_balanced: FAILED" in text
    assert "stock: ok" in text
    assert JournalEntry.objects.filter(memo="test damage").exists()


def test_unknown_check_names_are_refused() -> None:
    with pytest.raises(ValueError, match="unknown checks"):
        integrity.run(["nope"])
