"""Random sequences of real service calls on Postgres; the books must match the documents.

Hypothesis draws a list of actions (uniformly) with a seed each: order, invoice (with an
insurance split) and pay; deposit cash or a transfer; spend credit; confirm or reject a
transfer (also after its shift closed); perform, authorize or cancel a line; credit one unit;
approve or pay a refund; dispense (in parts, closing a remainder); hand cash over (to the
safe, the bank, a supervisor or the next shift) and receive or cancel it; merge the two
patients' files; close the shift and open the next; switch the partial-payment policy. A
refused call (``DomainError``) must leave nothing behind; a database error (trigger or
constraint) fails the test. After every action:

* the commit-time triggers pass (``SET CONSTRAINTS ALL IMMEDIATE``) and the trial balance
  is zero;
* each invoice's patient receivable in the ledger equals its outstanding from documents;
* each patient's credit in the ledger equals receipts - allocations - refunds paid;
* each billed service line is settled exactly when it owes nothing (credited when fully
  credited); work lists hold only settled or authorized lines;
* each open shift's ledger cash equals its drawer (expected cash); each closed shift's ledger
  cash is zero and its counted cash went to the safe (ADR 0006);
* a closed shift's report is exactly the one taken when it closed (invariant 3);
* no drug line has more units dispensed than billed and not credited (invariant 1), and a
  cancelled line never has dispensed units.

Each example runs in a savepoint that is rolled back.
"""

from __future__ import annotations

import itertools
import os
import random
from collections import Counter
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection, transaction
from django.db.models import Sum
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from apps.billing import services as billing
from apps.billing.models import Invoice, InvoiceLine
from apps.core.models import Policy
from apps.core.tests import builders as b
from apps.ledger import services as ledger
from apps.orders import services as orders
from apps.orders.models import ServiceLine
from apps.payments import services as pay
from apps.payments.models import Allocation, Bank, CashHandover, Payment, Refund, Shift
from apps.payments.tests import fin
from apps.pharmacy import services as ps
from apps.pharmacy.models import Batch, Item, Store
from domain.errors import DomainError

D = Decimal
pytestmark = pytest.mark.django_db
_refs = itertools.count(1)

#: Outcome counts across examples (``label: ok`` or ``label: CODE``), for inspection.
OUTCOMES: Counter[str] = Counter()


class Engine:
    """One clinic with two patients (one insured), a cashier and a supervisor."""

    def __init__(self) -> None:
        fin.seed()
        self.cashier = fin.staff("cashier")
        self.supervisor = fin.staff("cashier_supervisor")
        self.accountant = fin.staff("accountant")  # approves refunds the supervisor asked for
        self.pharmacist = fin.staff("pharmacist")
        self.admin = fin.staff("admin")
        self.doctor = fin.staff("doctor")
        self.bank = Bank.objects.get(code="BOK")
        insurer = fin.payer(percent="70", service_kind="lab")
        self.services = [
            fin.priced("lab", "100.00"),
            fin.priced("procedure", "35.50"),
            fin.priced("drug", "7.25"),
        ]
        self.patients = [fin.patient(), fin.patient()]
        self.visits = [fin.visit(self.patients[0], payer_obj=insurer), fin.visit(self.patients[1])]
        self.shift = pay.open_shift(self.cashier, D("100.00"))
        self.sup_shift = pay.open_shift(self.supervisor, D("0.00"))
        self.reports: dict[int, pay.ShiftSummary] = {}
        drug = self.services[2]
        self.store = Store.objects.create(
            code=f"RW{next(_refs)}", name_ar="صيدلية", name_en="Pharmacy", allows_dispense=True
        )
        item = Item.objects.create(
            service=drug,
            generic_name="Paracetamol",
            base_unit_code="tablet",
            base_unit_name_ar="حبة",
            base_unit_name_en="tablet",
        )
        batch = Batch.objects.create(
            item=item, batch_no="RW1", expiry_date=date(2030, 1, 1), unit_cost=D("1.0000")
        )
        b.stock_move(batch, self.store, "100000")

    # --- helpers -----------------------------------------------------------------------

    def _try(self, label: str, call: Callable[[], Any]) -> Any:
        try:
            result = call()
        except DomainError as exc:
            OUTCOMES[f"{label}: {exc.code}"] += 1
            return None
        OUTCOMES[f"{label}: ok"] += 1
        return result

    @staticmethod
    def _cents(r: random.Random) -> Decimal:
        return D(r.randint(1, 30000)) / 100

    def _pay(self, p: int, method: str, amount: Decimal) -> None:
        extra: dict[str, Any] = {}
        if method == "bank_transfer":
            extra = {"bank": self.bank, "reference": f"M-{next(_refs)}"}
        self._try(
            method,
            lambda: pay.record_payment(
                self.shift, self.patients[p], method, amount, actor=self.cashier, auto=True, **extra
            ),
        )

    def _open_lines(self) -> list[ServiceLine]:
        return list(
            ServiceLine.objects.filter(fulfilment_status__in=["pending", "in_progress"]).order_by(
                "id"
            )
        )

    def _transfers(self, *statuses: str) -> list[Payment]:
        return list(
            Payment.objects.filter(
                method="bank_transfer", reversal_of__isnull=True, verification__in=statuses
            ).order_by("id")
        )

    # --- actions -----------------------------------------------------------------------

    def bill(self, r: random.Random) -> None:
        p = r.randrange(2)
        items = [(self.services[r.randrange(3)], r.randint(1, 3)) for _ in range(r.randint(1, 3))]
        fin.order(self.visits[p], self.doctor, *items)
        inv = self._try("invoice", lambda: fin.invoice(self.visits[p], self.cashier))
        method = r.choice(["cash", "bank_transfer", "none"])
        if inv is None or method == "none":
            return
        due = billing.invoice_position(inv).outstanding
        self._pay(p, method, due if due > 0 and r.random() < 0.7 else self._cents(r))

    def deposit(self, r: random.Random) -> None:
        self._pay(r.randrange(2), r.choice(["cash", "bank_transfer"]), self._cents(r))

    def policy(self, r: random.Random) -> None:
        Policy.objects.update(allow_partial_payment=r.random() < 0.5)

    def spend_credit(self, r: random.Random) -> None:
        patient = self.patients[r.randrange(2)]
        opened = billing.open_invoices(patient)
        spendable = pay.spendable_credit(patient)
        if opened and spendable > 0:
            amount = min(spendable, opened[0][1].outstanding)
            self._try(
                "credit",
                lambda: pay.record_payment(
                    self.shift, patient, "patient_credit", amount, actor=self.cashier
                ),
            )

    def confirm(self, r: random.Random) -> None:
        pending = self._transfers("pending")
        if pending:
            t = r.choice(pending)
            self._try("confirm", lambda: pay.confirm_transfer(t, actor=self.supervisor, note="ok"))

    def reject(self, r: random.Random) -> None:
        live = self._transfers("pending", "confirmed")
        if live:
            t = r.choice(live)
            self._try(
                "reject",
                lambda: pay.reject_transfer(t, actor=self.supervisor, reason="NOT_RECEIVED"),
            )

    def perform(self, r: random.Random) -> None:
        lines = self._open_lines()
        if lines:
            line = r.choice(lines)
            self._try("perform", lambda: orders.perform_line(line, self.doctor))

    def authorize(self, r: random.Random) -> None:
        lines = [ln for ln in self._open_lines() if ln.billing_status != "settled"]
        if lines:
            line = r.choice(lines)
            self._try(
                "authorize",
                lambda: orders.authorize_perform_first(
                    [line], actor=self.supervisor, reason="EMERGENCY"
                ),
            )

    def cancel(self, r: random.Random) -> None:
        lines = self._open_lines()
        if lines:
            line = r.choice(lines)
            refund = r.random() < 0.5
            self._try(
                "cancel",
                lambda: orders.cancel_line(
                    line, "ORDER_ERROR", self.supervisor, open_refund=refund
                ),
            )

    def credit_one_unit(self, r: random.Random) -> None:
        lines = list(
            InvoiceLine.objects.filter(frozen=True)
            .exclude(service_line__billing_status="credited")
            .select_related("invoice")
            .order_by("id")
        )
        if not lines:
            return
        il = r.choice(lines)

        def credit() -> Any:
            cn = billing.create_credit_note(
                il.invoice, [(il, 1)], actor=self.supervisor, reason="PRICE_ERROR"
            )
            return billing.approve_credit_note(cn, actor=self.supervisor, open_refund=True)

        self._try("credit_note", credit)

    def refund(self, r: random.Random) -> None:
        open_refunds = list(
            Refund.objects.filter(status__in=["requested", "approved"]).order_by("id")
        )
        if not open_refunds:
            return
        refund = r.choice(open_refunds)
        if refund.status == "requested":
            approver = r.choice([self.supervisor, self.accountant])  # never the requester
            self._try("approve_refund", lambda: pay.approve_refund(refund, actor=approver))
        else:
            self._try("pay_refund", lambda: pay.pay_refund(refund, actor=self.cashier))

    def dispense(self, r: random.Random) -> None:
        lines = [ln for ln in ps.dispense_worklist() if ln.remaining > 0]  # type: ignore[attr-defined]
        if not lines:
            return
        line = r.choice(lines)
        qty = r.randint(1, int(line.remaining))  # type: ignore[attr-defined]
        complete = r.random() < 0.3
        self._try(
            "dispense",
            lambda: ps.dispense(
                visit=line.visit,
                store=self.store,
                actor=self.pharmacist,
                approver=self.supervisor,
                requests=[
                    ps.DispenseRequest(service_line_id=line.pk, quantity=qty, complete=complete)
                ],
            ),
        )

    def handover(self, r: random.Random) -> None:
        cash = pay.expected_cash(self.shift)
        if cash <= 0:
            return
        amount = min(cash, self._cents(r))
        destination = r.choice(["safe", "bank_deposit", "supervisor", "next_shift"])
        to_shift = self.sup_shift if destination == "next_shift" else None
        handover = self._try(
            f"handover {destination}",
            lambda: pay.cash_handover(
                self.shift,
                amount,
                destination,
                actor=self.cashier,
                to_shift=to_shift,
                bank_reference=f"DEP-{next(_refs)}" if destination == "bank_deposit" else "",
            ),
        )
        if handover is None:
            return
        if destination == "next_shift" and r.random() < 0.7:
            self._try("receive", lambda: pay.receive_handover(handover, actor=self.supervisor))
        elif r.random() < 0.3:
            self._try(
                "cancel_handover",
                lambda: pay.cancel_handover(handover, actor=self.cashier, note="recounted"),
            )

    def merge(self, r: random.Random) -> None:
        """The two patients turn out to be one person (FEATURES 1.4): their money stays
        usable, new money goes to the surviving file only."""
        from apps.patients import services as patients

        if self.patients[1].merged_into_id is None and r.random() < 0.5:
            self._try(
                "merge",
                lambda: patients.merge_patients(
                    self.patients[1], self.patients[0], actor=self.admin, reason_note="same"
                ),
            )
            self.patients[1].refresh_from_db()

    def close_and_reopen(self, r: random.Random) -> None:
        cents = r.choice([0, 0, r.randint(-500, 500)])
        counted = max(pay.expected_cash(self.shift) + D(cents) / 100, D("0.00"))
        pay.close_shift(
            self.shift, counted, actor=self.cashier, reason="COUNTING_ERROR" if cents else None
        )
        OUTCOMES["close: ok"] += 1
        self.reports[self.shift.pk] = pay.shift_summary(self.shift)
        self.shift = pay.open_shift(self.cashier, counted)

    # --- invariants --------------------------------------------------------------------

    def check(self) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
        assert ledger.trial_balance().balanced
        for patient in self.patients:
            fin.assert_positions_match_ledger(patient)
            paid = Payment.objects.filter(patient=patient, reversal_of__isnull=True).exclude(
                method="patient_credit"
            ).exclude(verification="rejected").aggregate(s=Sum("amount"))["s"] or D(0)
            allocated = Allocation.objects.filter(payment__patient=patient).aggregate(
                s=Sum("amount")
            )["s"] or D(0)
            refunded = Refund.objects.filter(patient=patient, status="paid").aggregate(
                s=Sum("amount")
            )["s"] or D(0)
            assert pay.credit_balance(patient) == paid - allocated - refunded
        lines = ServiceLine.objects.in_bulk()
        for inv in Invoice.objects.filter(status="approved"):
            for lp in billing.invoice_position(inv).lines:
                line = lines[lp.service_line_id]
                if lp.fully_credited:
                    assert line.billing_status == "credited"
                else:
                    expected = "settled" if lp.settled else "invoiced"
                    assert line.billing_status == expected, (line.pk, lp)
        for line in orders.worklist(["lab", "procedure", "drug"]):
            assert line.billing_status == "settled" or line.authorization_id is not None
        for shift in Shift.objects.all():
            cash = ledger.account_balance("CASH", shift=shift)
            if shift.status == "closed":
                # Counted cash (expected + variance) was swept to the safe at close.
                assert cash == 0
                swept = sum(
                    (
                        ln.debit
                        for e in ledger.entries_for(ledger.dl.SourceType.SHIFT_SWEEP, shift.pk)
                        for ln in e.lines.all()
                        if ln.account.code == "CASH_SAFE"
                    ),
                    D(0),
                )
                assert swept == shift.counted_cash
                assert pay.shift_summary(shift) == self.reports[shift.pk]
            else:
                assert cash == pay.expected_cash(shift), shift.pk
        for line in ServiceLine.objects.filter(kind="drug"):
            given = ps.dispensed_quantity(line)
            if line.fulfilment_status in ("pending", "in_progress"):
                # Units still open: credited (refunded) units are never handed out.
                credited = billing.credited_quantity(line)
                assert given + credited <= line.quantity, (line.pk, given, credited)
            if line.fulfilment_status == "cancelled":
                assert given == 0, line.pk
            if line.fulfilment_status == "performed" and line.performed_quantity is not None:
                assert given <= line.performed_quantity or given == 0, line.pk
        assert not CashHandover.objects.filter(
            to_shift__status="closed", received_at__isnull=True, cancelled_at__isnull=True
        ).exists()


ACTIONS = (
    "bill",
    "deposit",
    "policy",
    "spend_credit",
    "confirm",
    "reject",
    "perform",
    "authorize",
    "cancel",
    "credit_one_unit",
    "refund",
    "dispense",
    "handover",
    "merge",
    "close_and_reopen",
)
_CI = os.environ.get("HYPOTHESIS_PROFILE") == "ci"
_STEPS = 60 if _CI else 30


@settings(
    max_examples=25 if _CI else 8,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(seed=st.integers(0, 2**32 - 1), length=st.integers(_STEPS // 2, _STEPS))
def test_random_walks_keep_books_and_documents_in_step(seed: int, length: int) -> None:
    """A seeded walk: actions are drawn uniformly, so long sequences reach every money path.

    A failure reports ``seed`` and ``length``; the walk replays exactly from them.
    """
    r = random.Random(seed)
    with transaction.atomic():
        engine = Engine()
        for _ in range(length):
            getattr(engine, r.choice(ACTIONS))(r)
            engine.check()
        transaction.set_rollback(True)
