"""Append-only, balanced double-entry ledger (ARCHITECTURE 4.7)."""

from __future__ import annotations

import importlib
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.tests import builders as b
from apps.ledger.chart import ACCOUNT_CODES, CHART, ensure_chart_of_accounts
from apps.ledger.models import Account, JournalEntry, JournalLine

pytestmark = pytest.mark.django_db

EXPECTED_CODES = {
    "CASH",
    "BANK_PENDING",
    "BANK",
    "AR_PATIENT",
    "AR_PAYER",
    "PATIENT_CREDIT",
    "REVENUE",
    "DISCOUNT",
    "WRITE_OFF",
    "CASH_OVER_SHORT",
    "CASH_SAFE",  # ADR 0006: cash in the safe or in transit between drawers
}


def test_chart_matches_architecture_and_migration_copy() -> None:
    assert ACCOUNT_CODES == EXPECTED_CODES
    migration = importlib.import_module("apps.ledger.migrations.0003_seed_accounts")
    added = importlib.import_module("apps.ledger.migrations.0005_seed_cash_safe")
    assert [tuple(row) for row in [*migration.CHART, *added.ADDED]] == [
        (a.code, a.name_ar, a.name_en, a.kind, a.normal_balance) for a in CHART
    ]


def test_chart_is_seeded() -> None:
    ensure_chart_of_accounts()  # no-op on a fresh database, repairs a truncated one
    assert set(Account.objects.values_list("code", flat=True)) == EXPECTED_CODES
    assert ensure_chart_of_accounts() == 0
    assert Account.objects.get(code="PATIENT_CREDIT").normal_balance == "credit"
    assert all(a.name_ar and a.name_en for a in Account.objects.all())


def _account(code: str) -> Account:
    ensure_chart_of_accounts()
    return Account.objects.get(code=code)


def test_accounts_are_fixed() -> None:
    cash = _account("CASH")
    Account.objects.filter(pk=cash.pk).update(name_en="Cash drawer")  # names may change
    b.db_rejects(lambda: Account.objects.filter(pk=cash.pk).update(code="TILL"), "Cannot update")
    b.sql_rejects(
        "UPDATE ledger_account SET normal_balance = 'credit' WHERE id = %s",
        [cash.pk],
        "Cannot update",
    )
    b.db_rejects(lambda: Account.objects.filter(pk=cash.pk).delete(), "ACCOUNT_FIXED")
    b.sql_rejects("DELETE FROM ledger_account WHERE id = %s", [cash.pk], "ACCOUNT_FIXED")


def _entry(lines: list[tuple[str, str, str]], **dims: object) -> JournalEntry:
    entry = JournalEntry.objects.create(
        source_type="payment", source_id=1, entry_date=timezone.localdate()
    )
    for code, debit, credit in lines:
        JournalLine.objects.create(
            entry=entry,
            account=_account(code),
            debit=Decimal(debit),
            credit=Decimal(credit),
            **dims,
        )
    return entry


def test_balanced_entry_commits() -> None:
    sh = b.shift()
    pat = b.patient()
    with b.deferred_checks_fire(rejects=False):
        _entry([("CASH", "100.00", "0"), ("PATIENT_CREDIT", "0", "100.00")], shift=sh, patient=pat)


def test_unbalanced_entry_fails_at_commit() -> None:
    sh = b.shift()
    pat = b.patient()
    with b.deferred_checks_fire("JOURNAL_UNBALANCED"):
        _entry([("CASH", "100.00", "0"), ("PATIENT_CREDIT", "0", "90.00")], shift=sh, patient=pat)


def test_entry_without_lines_fails_at_commit() -> None:
    with b.deferred_checks_fire("JOURNAL_UNBALANCED"):
        _entry([])


def test_lines_added_later_cannot_unbalance_an_entry() -> None:
    sh = b.shift()
    pat = b.patient()
    entry = _entry(
        [("CASH", "100.00", "0"), ("PATIENT_CREDIT", "0", "100.00")], shift=sh, patient=pat
    )
    with b.deferred_checks_fire("JOURNAL_UNBALANCED"):
        JournalLine.objects.create(
            entry=entry, account=_account("BANK"), debit=Decimal("5"), credit=Decimal("0")
        )


def test_journal_is_append_only_orm_and_raw_sql() -> None:
    sh = b.shift()
    pat = b.patient()
    entry = _entry(
        [("CASH", "100.00", "0"), ("PATIENT_CREDIT", "0", "100.00")], shift=sh, patient=pat
    )
    line = entry.lines.first()
    assert line is not None
    b.db_rejects(lambda: JournalEntry.objects.filter(pk=entry.pk).update(memo="x"), "APPEND_ONLY")
    # (Model.delete() stops earlier on the PROTECT foreign key; the table refuses it anyway.)
    b.db_rejects(
        lambda: JournalEntry.objects.filter(pk=entry.pk)._raw_delete("default"), "APPEND_ONLY"
    )
    b.db_rejects(
        lambda: JournalLine.objects.filter(pk=line.pk).update(debit=Decimal("1")), "APPEND_ONLY"
    )
    b.db_rejects(lambda: JournalLine.objects.filter(pk=line.pk).delete(), "APPEND_ONLY")
    b.sql_rejects(
        "UPDATE ledger_journalentry SET source_id = 2 WHERE id = %s", [entry.pk], "APPEND_ONLY"
    )
    b.sql_rejects("DELETE FROM ledger_journalentry WHERE id = %s", [entry.pk], "APPEND_ONLY")
    b.sql_rejects(
        "UPDATE ledger_journalline SET credit = 1 WHERE id = %s", [line.pk], "APPEND_ONLY"
    )
    b.sql_rejects("DELETE FROM ledger_journalline WHERE id = %s", [line.pk], "APPEND_ONLY")


def test_line_is_one_sided_and_non_zero() -> None:
    bank = _account("BANK")
    with b.rolled_back():
        entry = JournalEntry.objects.create(
            source_type="payment", source_id=1, entry_date=timezone.localdate()
        )
        for debit, credit in (("10", "10"), ("0", "0"), ("-5", "0")):
            with pytest.raises(IntegrityError, match="ledger_line_one_side"), transaction.atomic():
                JournalLine.objects.create(
                    entry=entry, account=bank, debit=Decimal(debit), credit=Decimal(credit)
                )


@pytest.mark.parametrize(
    ("code", "missing"),
    [
        ("AR_PATIENT", "patient"),
        ("PATIENT_CREDIT", "patient"),
        ("AR_PAYER", "payer"),
        ("WRITE_OFF", "payer"),
        ("CASH", "shift"),
        ("CASH_OVER_SHORT", "shift"),
    ],
)
def test_lines_carry_the_dimension_their_account_needs(code: str, missing: str) -> None:
    account = _account(code)

    def post() -> None:
        entry = JournalEntry.objects.create(
            source_type="invoice", source_id=1, entry_date=timezone.localdate()
        )
        JournalLine.objects.create(
            entry=entry, account=account, debit=Decimal("1"), credit=Decimal("0")
        )

    b.db_rejects(post, f"JOURNAL_DIMENSION: {code} lines need a {missing}")


def test_source_type_is_a_known_document() -> None:
    with (
        pytest.raises(IntegrityError, match="ledger_entry_source_type_valid"),
        transaction.atomic(),
    ):
        JournalEntry.objects.create(
            source_type="manual", source_id=1, entry_date=timezone.localdate()
        )
