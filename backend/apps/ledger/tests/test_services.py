"""Ledger services: storing balanced drafts and reading balances (ARCHITECTURE 4.7)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import DatabaseError, transaction

from apps.core.tests import builders as b
from apps.ledger import services as ledger
from apps.ledger.models import JournalEntry, JournalLine
from apps.payments.tests import fin
from domain import ledger as dl
from domain.errors import DomainError
from domain.payments import PaymentMethod

D = Decimal
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _seed() -> None:
    fin.seed()


def test_post_stores_lines_with_dimensions() -> None:
    patient, payer, dept = b.patient(), b.payer(), b.department()
    inv = b.approved_invoice()
    actor = fin.staff("cashier")
    draft = dl.post_invoice_approved(
        inv.pk,
        patient.pk,
        [
            dl.RevenueLine(
                D("100.00"), D("10.00"), D("60.00"), D("30.00"), payer.pk, dept.pk, "lab"
            ),
            dl.RevenueLine(
                D("20.00"), D("0.00"), D("0.00"), D("20.00"), None, ledger.NO_DEPARTMENT, "drug"
            ),
        ],
    )
    entry = ledger.post(draft, actor=actor)
    assert entry is not None
    assert (entry.source_type, entry.source_id, entry.posted_by) == ("invoice", inv.pk, actor)
    lines = {(ln.account.code, ln.service_kind): ln for ln in entry.lines.select_related("account")}
    assert lines[("AR_PATIENT", "")].patient == patient
    assert lines[("AR_PATIENT", "")].invoice == inv
    assert lines[("AR_PATIENT", "")].debit == D("50.00")
    assert lines[("AR_PAYER", "")].payer == payer
    assert lines[("REVENUE", "lab")].department == dept
    assert lines[("REVENUE", "drug")].department is None
    assert ledger.account_balance("REVENUE") == D("120.00")
    assert ledger.account_balance("REVENUE", department=dept) == D("100.00")
    assert ledger.account_balance("REVENUE", service_kind="drug") == D("20.00")
    assert ledger.account_balance("AR_PATIENT", patient=patient, invoice=inv.pk) == D("50.00")
    assert ledger.account_balance("DISCOUNT") == D("10.00")
    assert ledger.entries_for(dl.SourceType.INVOICE, inv.pk) == [entry]


def test_balances_follow_the_normal_side_and_trial_balance_is_zero() -> None:
    patient = b.patient()
    sh = b.shift()
    ledger.post(dl.post_payment_received(1, patient.pk, PaymentMethod.CASH, D("70.00"), sh.pk))
    ledger.post(dl.post_refund(2, patient.pk, D("20.00"), sh.pk))
    assert ledger.account_balance("CASH", shift=sh) == D("50.00")
    assert ledger.account_balance("PATIENT_CREDIT", patient=patient) == D("50.00")  # credit side
    tb = ledger.trial_balance()
    assert tb.balanced
    assert (tb.total_debit, tb.total_credit, tb.total) == (D("90.00"), D("90.00"), D("0.00"))
    assert tb.rows == {"CASH": D("50.00"), "PATIENT_CREDIT": D("-50.00")}
    with pytest.raises(ValueError, match="Unknown ledger dimensions"):
        ledger.account_balance("CASH", till=1)


def test_empty_draft_posts_nothing() -> None:
    assert ledger.post(dl.post_shift_variance(b.shift().pk, D("0.00"))) is None
    assert not JournalEntry.objects.exists()


def test_unbalanced_draft_is_refused_before_the_database() -> None:
    draft = dl.JournalDraft(
        dl.SourceType.REFUND,
        1,
        (
            dl.JournalLine(dl.Account.BANK, debit=D("5.00")),
            dl.JournalLine(dl.Account.BANK_PENDING, credit=D("4.00")),
        ),
    )
    with pytest.raises(DomainError) as exc:
        ledger.post(draft)
    assert exc.value.code == "JOURNAL_UNBALANCED"
    assert not JournalEntry.objects.exists()


def test_missing_chart_account_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ledger, "_accounts", dict)
    with pytest.raises(DomainError) as exc:
        ledger.post(dl.post_transfer_confirmed(1, D("5.00")))
    assert exc.value.code == "LEDGER_ACCOUNT_MISSING"
    assert exc.value.details["accounts"] == ["BANK", "BANK_PENDING"]


def test_posted_entries_never_change() -> None:
    entry = ledger.post(dl.post_transfer_confirmed(9, D("5.00")))
    assert entry is not None
    with pytest.raises(DatabaseError, match="APPEND_ONLY"), transaction.atomic():
        JournalLine.objects.filter(entry=entry).update(debit=D("6.00"))
    b.sql_rejects("DELETE FROM ledger_journalentry WHERE id = %s", [entry.pk], "APPEND_ONLY")
