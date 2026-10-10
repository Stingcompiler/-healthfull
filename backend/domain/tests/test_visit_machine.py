"""Stateful simulation of a patient's visits across every money and stock rule.

Random sequences of: ordering lines, perform-first authorizations, cancellations, invoices
(coverage, discounts, two price-list versions), payments (cash, transfers, QR, duplicate
references), spending patient credit, later allocations, transfer confirmation and
rejection (also after the shift closed), credit notes (partial and full) with
de-allocation, refunds, shift close with variance, claims (submit, respond, payer payment,
rebill, write-off), stock receipts, counts, and work on lines (start, perform, dispense).

After every step the invariants are checked against a ledger built only from the domain
posting builders and against positions computed only from documents:

* every journal entry balances;
* patient receivable per ledger equals the outstanding of every invoice from documents;
* payer receivable per ledger equals the claim lines' receivable;
* patient credit per ledger equals receipts - allocations - refunds;
* payer share never reaches CASH/BANK except through a payer payment (invariant 7);
* settled lines are exactly the lines fully covered (and only they reach work lists with
  authorized ones; invariant 1);
* allocations stay within their payments; a rejected payment keeps none;
* stock never goes negative and only dispensing removes it for patients (invariant 5);
* a closed shift never receives anything (invariant 3).

Each rule is a thin wrapper that draws arguments and calls an ``act_*`` method, so the
scenario tests at the end can drive rare paths deterministically through the same code
and invariants (Hypothesis enables a random subset of rules per run, so long chains are
rare in the random runs).
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from hypothesis import HealthCheck, currently_in_test_context, event, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
)

from domain import allocation as al
from domain import claims as cl
from domain import ledger as lg
from domain import service_line as sl
from domain import shift as sh
from domain import stock as sk
from domain.audit import Approval
from domain.coverage import CoverageRule, check_discount, payer_share_for
from domain.errors import DomainError
from domain.invoice import (
    BillableLine,
    CreditLineDraft,
    InvoiceLineDraft,
    InvoicePosition,
    Rebill,
    build_credit_line,
    build_invoice_lines,
    credited_quantity,
    invoice_position,
)
from domain.money import ZERO, q
from domain.payments import (
    REFERENCE_METHODS,
    PaymentMethod,
    Verification,
    check_reference,
    confirm,
    initial_verification,
    reject,
    validate_payment,
)
from domain.pricing import ItemKey, PriceVersion, unit_price

PATIENT = 1
PAYER = 7
DEPARTMENT = 3
DRUG_ITEM = 1
STORE = 1
D0 = date(2026, 10, 1)
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
TODAY = date(2026, 10, 7)
KINDS = {"CONS": "consultation", "CBC": "lab", "INJ": "procedure", "AMOX": "drug"}
CASH_PRICES: dict[ItemKey, Decimal] = {
    "CONS": Decimal("5000.00"),
    "CBC": Decimal("3000.00"),
    "INJ": Decimal("1500.00"),
    "AMOX": Decimal("120.50"),
}
CASH_LIST = (
    PriceVersion(1, D0, CASH_PRICES),
    PriceVersion(
        2, D0 + timedelta(days=10), {k: q(v * Decimal("1.1")) for k, v in CASH_PRICES.items()}
    ),
)
PAYER_LIST = (PriceVersion(3, D0, {k: q(v * Decimal("1.2")) for k, v in CASH_PRICES.items()}),)
RULES = (
    CoverageRule.percentage(Decimal(70)),
    CoverageRule.fixed_copay(Decimal("1000.00")),
    CoverageRule.capped(Decimal("2500.00"), payer_percent=Decimal(80)),
)
LIMITS: dict[str, Decimal | int] = {"cashier": 0, "cashier_supervisor": 25, "manager": 100}
DISCOUNTS = (ZERO, ZERO, Decimal("0.1"), Decimal("0.3"), Decimal(1))
#: batch id -> expiry; batch 1 is expired and must never be dispensed.
BATCHES = {
    1: TODAY - timedelta(days=3),
    2: TODAY + timedelta(days=20),
    3: TODAY + timedelta(days=200),
    4: None,
}

money_st = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("20000"), places=2)


def note(name: str) -> None:
    """Record a Hypothesis event (shown by ``--hypothesis-show-statistics``) when in a run."""
    if currently_in_test_context():
        event(name)


def attempt[T](fn: Callable[[], T]) -> T | DomainError:
    try:
        return fn()
    except DomainError as exc:
        return exc


@dataclass
class MLine:
    id: int
    item: str
    quantity: int
    status: sl.LineStatus
    covered: bool
    rule_index: int
    invoice_id: int | None = None


@dataclass
class MInvoice:
    id: int
    approved_at: datetime
    lines: tuple[InvoiceLineDraft, ...]
    credits: list[CreditLineDraft] = field(default_factory=list)
    rebills: list[Rebill] = field(default_factory=list)


@dataclass
class MPayment:
    id: int
    method: PaymentMethod
    amount: Decimal
    verification: Verification
    shift_id: int


@dataclass
class MShift:
    id: int
    opening: Decimal
    open: bool = True
    journal_mark: int = 0
    payments_at_close: int = 0
    refunds_at_close: int = 0


@dataclass
class MCreditNote:
    id: int
    created_credit: Decimal
    refunded: Decimal = ZERO


@dataclass
class MRefund:
    id: int
    amount: Decimal
    shift_id: int


class VisitMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.allow_partial = False
        self._ids = itertools.count(1)
        self._clock = 0
        self.lines: dict[int, MLine] = {}
        self.invoices: dict[int, MInvoice] = {}
        self.payments: dict[int, MPayment] = {}
        self.rows: list[tuple[int, int, Decimal, int]] = []  # payment, invoice, amount, seq
        self.shifts: dict[int, MShift] = {}
        self.current: int | None = None
        self.credit_notes: dict[int, MCreditNote] = {}
        self.refunds: list[MRefund] = []
        self.variances: list[Decimal] = []
        self.payer_paid = ZERO
        self.claims: dict[tuple[int, int], cl.ClaimLine] = {}
        self.stock: dict[sk.StockKey, int] = {}
        self.moves: list[sk.StockMoveDraft] = []
        self.dispensed: dict[int, int] = {}
        self.journals: list[lg.JournalDraft] = []
        self.uncovered = ZERO
        self.refs: set[tuple[str, str]] = set()

    # --- helpers ---------------------------------------------------------------------

    def _id(self) -> int:
        return next(self._ids)

    def _now(self) -> datetime:
        self._clock += 1
        return T0 + timedelta(minutes=self._clock)

    def _ok(self) -> Approval:
        return Approval(approver_id=9, at=self._now(), reason="simulated")

    def _post(self, draft: lg.JournalDraft) -> None:
        lg.assert_balanced(draft)
        if not draft.is_empty:
            self.journals.append(draft)

    def _records(self) -> list[al.AllocationRecord]:
        return [
            al.AllocationRecord(
                payment_id=pid,
                invoice_id=iid,
                amount=amount,
                seq=seq,
                pending=self.payments[pid].verification is Verification.PENDING,
                from_credit=self.payments[pid].method is PaymentMethod.PATIENT_CREDIT,
            )
            for pid, iid, amount, seq in self.rows
        ]

    def _alloc(self, payment_id: int, invoice_id: int, amount: Decimal) -> None:
        seq = self._id()
        self.rows.append((payment_id, invoice_id, amount, seq))
        self._post(lg.post_allocation(seq, PATIENT, invoice_id, amount))

    def position(self, invoice_id: int) -> InvoicePosition:
        inv = self.invoices[invoice_id]
        allocations = [amount for _, iid, amount, _ in self.rows if iid == inv.id]
        return invoice_position(inv.lines, inv.credits, allocations, inv.rebills)

    def _sync(self) -> None:
        for inv in self.invoices.values():
            for lp in self.position(inv.id).lines:
                line = self.lines[lp.service_line_id]
                line.status = sl.apply_settlement(line.status, outstanding=lp.outstanding)

    def credit_balance(self) -> Decimal:
        received = sum(
            (
                p.amount
                for p in self.payments.values()
                if p.method is not PaymentMethod.PATIENT_CREDIT
                and p.verification is not Verification.REJECTED
            ),
            ZERO,
        )
        allocated = sum((amount for _, _, amount, _ in self.rows), ZERO)
        refunded = sum((r.amount for r in self.refunds), ZERO)
        return received - allocated - refunded

    def pending_unallocated(self) -> list[Decimal]:
        """The unallocated remainder of every transfer still awaiting verification."""
        nets = al.net_by_payment(self._records())
        return [
            p.amount - nets.get(p.id, ZERO)
            for p in self.payments.values()
            if p.verification is Verification.PENDING
        ]

    def spendable(self) -> Decimal:
        return al.spendable_credit(self.credit_balance(), self.pending_unallocated())

    def _open_invoices(self) -> list[al.OpenInvoice]:
        out = []
        for inv in self.invoices.values():
            outstanding = self.position(inv.id).outstanding
            if outstanding > 0:
                out.append(al.OpenInvoice(inv.id, inv.approved_at, outstanding))
        return sorted(out, key=lambda i: (i.approved_at, i.invoice_id))

    def _expected_cash(self, shift_id: int) -> Decimal:
        s = self.shifts[shift_id]
        cash_in = sum(
            (
                p.amount
                for p in self.payments.values()
                if p.shift_id == shift_id and p.method is PaymentMethod.CASH
            ),
            ZERO,
        )
        refunds = sum((r.amount for r in self.refunds if r.shift_id == shift_id), ZERO)
        return sh.expected_cash(
            sh.CashMovements(opening_float=s.opening, cash_in=cash_in, cash_refunds=refunds)
        )

    def _allocate(self, payment_id: int, amount: Decimal, *, require_full: bool = False) -> Decimal:
        open_invoices = self._open_invoices()
        if not open_invoices:
            return ZERO
        plan = al.auto_allocate(amount, open_invoices, allow_partial=self.allow_partial)
        al.validate_allocations(
            amount,
            plan.allocations,
            {i.invoice_id: i.outstanding for i in open_invoices},
            allow_partial=self.allow_partial,
            require_full=require_full,
        )
        for a in plan.allocations:
            self._alloc(payment_id, a.invoice_id, a.amount)
        return plan.allocated

    def _billable_lines(self) -> list[MLine]:
        return [
            ln
            for ln in self.lines.values()
            if ln.status.billing is sl.BillingStatus.UNBILLED
            and ln.status.fulfilment is not sl.FulfilmentStatus.CANCELLED
        ]

    def _creditable(self) -> list[tuple[int, int]]:
        return [
            (inv.id, ln.position)
            for inv in self.invoices.values()
            for ln in inv.lines
            if credited_quantity(ln.position, inv.credits) < ln.quantity
        ]

    def _claims_in(self, *statuses: cl.ClaimLineStatus) -> list[tuple[int, int]]:
        return sorted(k for k, c in self.claims.items() if c.status in statuses)

    def _live_transfers(self) -> list[MPayment]:
        return [
            p
            for p in self.payments.values()
            if p.method in REFERENCE_METHODS and p.verification is not Verification.REJECTED
        ]

    # --- actions (explicit arguments; used by the rules and the scenarios) --------------

    def act_open_shift(self, opening: Decimal) -> int:
        open_count = sum(1 for s in self.shifts.values() if s.open)
        sh.validate_open(open_count, opening)
        sid = self._id()
        self.shifts[sid] = MShift(sid, opening)
        self.current = sid
        return sid

    def act_close_shift(self, delta: Decimal, *, explain: bool = True) -> bool:
        assert self.current is not None
        s = self.shifts[self.current]
        expected = self._expected_cash(s.id)
        counted = max(expected + delta, ZERO)
        result = attempt(
            lambda: sh.validate_close(
                sh.ShiftStatus.OPEN,
                expected=expected,
                counted=counted,
                explanation="note found later" if explain else "",
            )
        )
        if isinstance(result, DomainError):
            assert result.code == "VARIANCE_EXPLANATION_REQUIRED"
            assert counted != expected
            return False
        self._post(lg.post_shift_variance(s.id, result.variance))
        self.variances.append(result.variance)
        s.open = False
        s.journal_mark = len(self.journals)
        s.payments_at_close = sum(1 for p in self.payments.values() if p.shift_id == s.id)
        s.refunds_at_close = sum(1 for r in self.refunds if r.shift_id == s.id)
        self.current = None
        return True

    def act_order(self, item: str, qty: int, *, covered: bool = False, rule_index: int = 0) -> int:
        lid = self._id()
        quantity = qty * 10 if item == "AMOX" else qty
        self.lines[lid] = MLine(lid, item, quantity, sl.LineStatus(), covered, rule_index)
        return lid

    def act_authorize(self, line_id: int) -> bool:
        line = self.lines[line_id]
        result = attempt(lambda: sl.authorize(line.status, self._ok()))
        if isinstance(result, DomainError):
            return False
        line.status = result
        return True

    def act_cancel(self, line_id: int) -> None:
        line = self.lines[line_id]
        line.status = sl.cancel(line.status, self._ok())

    def act_work(self, line_id: int, action: str) -> bool:
        line = self.lines[line_id]
        eligible = sl.can_enter_worklist(line.status)
        moved = attempt(
            lambda: sl.start(line.status) if action == "start" else sl.perform(line.status)
        )
        if isinstance(moved, DomainError):
            assert not eligible or moved.code == "LINE_ALREADY_STARTED"
            return False
        # Invariant 1: no work without a settled line or a perform-first authorization.
        assert eligible
        if action == "perform" and line.item == "AMOX":
            batches = [
                sk.BatchStock(b, expiry, self.stock.get((DRUG_ITEM, b, STORE), 0))
                for b, expiry in BATCHES.items()
            ]
            picks = attempt(lambda: sk.select_batches(batches, line.quantity, TODAY))
            if isinstance(picks, DomainError):
                assert picks.code == "STOCK_INSUFFICIENT"
                return False
            assert all(sk.is_usable(BATCHES[p.batch_id], TODAY) for p in picks)
            moves = sk.dispense_moves(DRUG_ITEM, STORE, picks)
            self.stock = sk.apply_moves(self.stock, moves)
            self.moves.extend(moves)
            self.dispensed[line.id] = line.quantity
        line.status = moved
        return True

    def act_receive(self, batch: int, qty: int) -> None:
        move = sk.StockMoveDraft(DRUG_ITEM, batch, STORE, qty, sk.MoveKind.RECEIPT)
        self.stock = sk.apply_moves(self.stock, [move])
        self.moves.append(move)

    def act_count(self, batch: int, counted: int) -> None:
        book = self.stock.get((DRUG_ITEM, batch, STORE), 0)
        moves = sk.count_adjustments([sk.CountLine(DRUG_ITEM, batch, STORE, book, counted)])
        self.stock = sk.apply_moves(self.stock, moves)
        self.moves.extend(moves)
        assert self.stock.get((DRUG_ITEM, batch, STORE), 0) == counted

    def act_invoice(
        self,
        line_ids: Sequence[int],
        *,
        day: int = 0,
        discounts: Sequence[Decimal] = (),
        approver: str = "manager",
    ) -> int | None:
        on = D0 + timedelta(days=day)
        billables = []
        for i, line_id in enumerate(line_ids):
            line = self.lines[line_id]
            rule_ = RULES[line.rule_index] if line.covered else None
            versions = PAYER_LIST if line.covered else CASH_LIST
            gross = unit_price(versions, line.item, on) * line.quantity
            before = gross - payer_share_for(gross, rule_)
            discount = q(before * discounts[i]) if i < len(discounts) else ZERO
            approval = self._ok() if discount else None
            checked = attempt(
                lambda d=discount, b=before, a=approval: check_discount(  # type: ignore[misc]
                    d, b, [approver], LIMITS, a
                )
            )
            if isinstance(checked, DomainError):
                assert checked.code == "DISCOUNT_LIMIT_EXCEEDED"
                return None
            billables.append(
                BillableLine(
                    service_line_id=line.id,
                    item=line.item,
                    quantity=line.quantity,
                    status=line.status,
                    price_versions=versions,
                    payer_id=PAYER if line.covered else None,
                    coverage=rule_,
                    discount=discount,
                )
            )
        drafts = build_invoice_lines(billables, on)
        inv_id = self._id()
        revenue = []
        for d in drafts:
            # Invariant 6: the frozen price is the one effective on the approval day.
            assert d.unit_price == unit_price(billables[d.position - 1].price_versions, d.item, on)
            revenue.append(
                lg.RevenueLine(
                    d.gross,
                    d.discount,
                    d.payer_share,
                    d.patient_share,
                    d.payer_id,
                    DEPARTMENT,
                    KINDS[str(d.item)],
                )
            )
        self._post(lg.post_invoice_approved(inv_id, PATIENT, revenue))
        for d in drafts:
            line = self.lines[d.service_line_id]
            line.status = sl.invoice(line.status, patient_due=d.patient_share)
            # Rule 2: a line with nothing for the patient to pay settles at approval.
            assert (line.status.billing is sl.BillingStatus.SETTLED) == (d.patient_share == 0)
            line.invoice_id = inv_id
            if d.payer_share > 0:
                self.claims[(inv_id, d.position)] = cl.accrue(d.payer_share)
        self.invoices[inv_id] = MInvoice(inv_id, self._now(), drafts)
        self._sync()
        return inv_id

    def act_credit(self, invoice_id: int, position: int, qty: int) -> int | None:
        inv = self.invoices[invoice_id]
        ln = next(x for x in inv.lines if x.position == position)
        key = (inv.id, ln.position)
        claim = self.claims.get(key)
        locked = attempt(lambda: cl.require_creditable(claim))
        if isinstance(locked, DomainError):
            assert locked.code == "CLAIM_LINE_LOCKED"
            return None
        done = credited_quantity(ln.position, inv.credits)
        credit = build_credit_line(ln, qty, inv.credits)
        service_line = self.lines[ln.service_line_id]
        fully = done + qty == ln.quantity
        new_status = sl.credit(service_line.status, self._ok(), fully_credited=fully)
        cn_id = self._id()
        inv.credits.append(credit)
        if credit.payer_share > 0:
            assert claim is not None
            self.claims[key] = cl.reduce_for_credit(claim, credit.payer_share)
        revenue = lg.RevenueLine(
            credit.gross,
            credit.discount,
            credit.payer_share,
            credit.patient_share,
            credit.payer_id,
            DEPARTMENT,
            KINDS[str(ln.item)],
        )
        self._post(lg.post_credit_note(cn_id, inv.id, PATIENT, [revenue]))
        service_line.status = new_status
        excess = self.position(inv.id).over_allocation
        if excess:
            for d in al.deallocate_excess(inv.id, self._records(), excess):
                self._alloc(d.payment_id, d.invoice_id, d.amount)
        assert self.position(inv.id).over_allocation == 0
        self.credit_notes[cn_id] = MCreditNote(cn_id, excess)
        self._sync()
        return cn_id

    def act_pay(
        self,
        method: PaymentMethod,
        amount: Decimal,
        *,
        allocate: bool = True,
        reference: tuple[str, str] | None = None,
    ) -> int:
        assert self.current is not None
        bank: str | None = None
        ref: str | None = None
        if method in REFERENCE_METHODS:
            bank, ref = reference or ("BOK", f"trx-{self._id()}")
        details = validate_payment(method, amount, bank=bank, reference=ref)
        if details.bank is not None and details.reference is not None:
            b, r = details.bank, details.reference
            checked = attempt(lambda: check_reference(b, r, self.refs))
            if isinstance(checked, DomainError):
                assert checked.code == "DUPLICATE_REFERENCE"
                overridden = check_reference(
                    b, r, self.refs, override=self._ok(), can_override=True
                )
                assert overridden.duplicate
            self.refs.add((b, r))
        pid = self._id()
        self.payments[pid] = MPayment(
            pid, method, amount, initial_verification(method), self.current
        )
        self._post(lg.post_payment_received(pid, PATIENT, method, amount, self.current))
        if allocate:
            self._allocate(pid, amount)
        self._sync()
        return pid

    def act_spend_credit(self, amount: Decimal) -> int | None:
        assert self.current is not None
        spendable = self.spendable()
        open_invoices = self._open_invoices()
        if spendable == 0 or not open_invoices:
            return None
        plan = al.auto_allocate(
            min(amount, spendable), open_invoices, allow_partial=self.allow_partial
        )
        if plan.allocated == 0:
            return None
        al.validate_credit_spend(plan.allocated, spendable)
        method = PaymentMethod.PATIENT_CREDIT
        pid = self._id()
        self.payments[pid] = MPayment(
            pid, method, plan.allocated, initial_verification(method), self.current
        )
        self._post(lg.post_payment_received(pid, PATIENT, method, plan.allocated, self.current))
        assert self._allocate(pid, plan.allocated, require_full=True) == plan.allocated
        note("credit spent")
        self._sync()
        return pid

    def act_allocate_later(self, payment_id: int) -> Decimal:
        p = self.payments[payment_id]
        left = al.unallocated(p.amount, [r for r in self._records() if r.payment_id == p.id])
        limit = al.later_allocation_limit(
            left,
            pending=p.verification is Verification.PENDING,
            credit_balance=self.credit_balance(),
            spendable=self.spendable(),
        )
        if limit < left:
            note("later allocation capped by the credit pool")
        if limit == 0:
            return ZERO
        allocated = self._allocate(p.id, limit)
        self._sync()
        return allocated

    def act_confirm(self, payment_id: int) -> None:
        p = self.payments[payment_id]
        p.verification = confirm(p.method, p.verification, self._ok())
        self._post(lg.post_transfer_confirmed(p.id, p.amount))

    def act_reject(self, payment_id: int) -> al.RejectionPlan | None:
        p = self.payments[payment_id]
        status = sh.ShiftStatus.OPEN if self.shifts[p.shift_id].open else sh.ShiftStatus.CLOSED
        original = sh.ShiftRef(p.shift_id, status)
        current = (
            sh.ShiftRef(self.current, sh.ShiftStatus.OPEN) if self.current is not None else None
        )
        target = attempt(lambda: sh.late_effect_shift(original, current))
        if isinstance(target, DomainError):
            assert target.code == "SHIFT_NOT_OPEN"
            assert not self.shifts[p.shift_id].open
            assert self.current is None
            return None
        # Invariant 3: a late effect never lands in a closed shift.
        assert self.shifts[target].open
        was_confirmed = p.verification is Verification.CONFIRMED
        plan = al.plan_rejection(
            p.id, p.amount, self._records(), pending=not was_confirmed, spendable=self.spendable()
        )
        p.verification = reject(p.method, p.verification, self._ok())
        if not was_confirmed:
            # Pending money is never spent or refunded, so rejecting it never needs to claw
            # back credit used elsewhere.
            assert plan.recovery == ()
            assert plan.uncovered == 0
        if plan.recovery:
            note("rejection recovered spent credit")
        if plan.uncovered:
            note("rejection left the patient owing")
        for d in plan.reversals + plan.recovery:
            self._alloc(d.payment_id, d.invoice_id, d.amount)
        self._post(lg.post_transfer_rejected(p.id, PATIENT, p.amount, was_confirmed=was_confirmed))
        self.uncovered += plan.uncovered
        self._sync()
        return plan

    def act_refund(self, credit_note_id: int, amount: Decimal) -> bool:
        assert self.current is not None
        shift_id = self.current
        cn = self.credit_notes[credit_note_id]
        source = cn.created_credit - cn.refunded
        allowed = attempt(
            lambda: al.validate_refund(
                amount, source_available=source, spendable=self.spendable(), approval=self._ok()
            )
        )
        if isinstance(allowed, DomainError):
            assert allowed.code in ("REFUND_EXCEEDS_CREDIT", "REFUND_EXCEEDS_SOURCE")
            return False
        cash = attempt(lambda: sh.ensure_cash_available(amount, self._expected_cash(shift_id)))
        if isinstance(cash, DomainError):
            assert cash.code == "CASH_INSUFFICIENT"
            return False
        rid = self._id()
        self.refunds.append(MRefund(rid, amount, shift_id))
        cn.refunded += amount
        self._post(lg.post_refund(rid, PATIENT, amount, shift_id))
        return True

    def act_submit_claim(self, key: tuple[int, int]) -> None:
        self.claims[key] = cl.submit(self.claims[key])

    def act_respond_claim(self, key: tuple[int, int], share: int) -> None:
        line = self.claims[key]
        self.claims[key] = cl.respond(line, q(line.amount * share / 100), reason="payer decision")

    def act_payer_payment(self, key: tuple[int, int], amount: Decimal) -> None:
        line = self.claims[key]
        cl.validate_payer_payment(amount, {1: amount}, {1: line})
        ppid = self._id()
        self._post(lg.post_payer_payment(ppid, PAYER, [(key[0], amount)]))
        self.claims[key] = cl.record_payment(line, amount)
        self.payer_paid += amount

    def act_resolve_rejection(self, key: tuple[int, int], *, rebill: bool) -> None:
        line = self.claims[key]
        amount = line.unresolved_rejection
        resolution = cl.Resolution.REBILLED if rebill else cl.Resolution.WRITTEN_OFF
        self.claims[key] = cl.resolve_rejection(line, resolution, self._ok())
        sid = self._id()
        if rebill:
            self._post(lg.post_payer_rebill(sid, PATIENT, PAYER, key[0], amount))
            self.invoices[key[0]].rebills.append(Rebill(key[1], amount))
            self._sync()
        else:
            self._post(lg.post_payer_write_off(sid, PAYER, key[0], amount))

    # --- rules -------------------------------------------------------------------------------

    @initialize(allow_partial=st.booleans(), opening=money_st)
    def setup(self, allow_partial: bool, opening: Decimal) -> None:
        self.allow_partial = allow_partial
        self.act_open_shift(opening)

    @rule(
        opening=money_st,
        delta=st.decimals(min_value=-500, max_value=500, places=2),
        explain=st.booleans(),
    )
    def shift_turn(self, opening: Decimal, delta: Decimal, explain: bool) -> None:
        """Close the open shift (counted cash = expected + delta), or open a new one."""
        if self.current is None:
            self.act_open_shift(opening)
        else:
            self.act_close_shift(delta, explain=explain)

    @rule(
        item=st.sampled_from(sorted(KINDS)),
        qty=st.integers(1, 3),
        covered=st.booleans(),
        rule_index=st.integers(0, len(RULES) - 1),
    )
    def order(self, item: str, qty: int, covered: bool, rule_index: int) -> None:
        self.act_order(item, qty, covered=covered, rule_index=rule_index)

    @precondition(lambda self: bool(self.lines))
    @rule(data=st.data())
    def authorize(self, data: st.DataObject) -> None:
        self.act_authorize(data.draw(st.sampled_from(sorted(self.lines))))

    @precondition(
        lambda self: any(
            ln.status.billing is sl.BillingStatus.UNBILLED
            and ln.status.fulfilment in sl.ACTIVE_FULFILMENT
            for ln in self.lines.values()
        )
    )
    @rule(data=st.data())
    def cancel_unbilled(self, data: st.DataObject) -> None:
        candidates = [
            ln.id
            for ln in self.lines.values()
            if ln.status.billing is sl.BillingStatus.UNBILLED
            and ln.status.fulfilment in sl.ACTIVE_FULFILMENT
        ]
        self.act_cancel(data.draw(st.sampled_from(candidates)))

    @precondition(
        lambda self: any(ln.status.fulfilment in sl.ACTIVE_FULFILMENT for ln in self.lines.values())
    )
    @rule(data=st.data(), action=st.sampled_from(["start", "perform"]))
    def work(self, data: st.DataObject, action: str) -> None:
        candidates = [
            ln.id for ln in self.lines.values() if ln.status.fulfilment in sl.ACTIVE_FULFILMENT
        ]
        self.act_work(data.draw(st.sampled_from(candidates)), action)

    @rule(batch=st.sampled_from(sorted(BATCHES)), receive=st.booleans(), data=st.data())
    def stock_step(self, batch: int, receive: bool, data: st.DataObject) -> None:
        """Receive goods into a batch, or count it and post the variance."""
        if receive:
            self.act_receive(batch, data.draw(st.integers(1, 60)))
        else:
            book = self.stock.get((DRUG_ITEM, batch, STORE), 0)
            self.act_count(batch, data.draw(st.integers(0, book + 5)))

    @precondition(lambda self: bool(self._billable_lines()))
    @rule(
        data=st.data(),
        day=st.integers(0, 20),
        approver=st.sampled_from(["cashier", "cashier_supervisor", "manager", "manager"]),
    )
    def invoice(self, data: st.DataObject, day: int, approver: str) -> None:
        ids = [ln.id for ln in self._billable_lines()]
        chosen = data.draw(st.lists(st.sampled_from(ids), min_size=1, unique=True))
        discounts = [data.draw(st.sampled_from(DISCOUNTS)) for _ in chosen]
        self.act_invoice(chosen, day=day, discounts=discounts, approver=approver)

    @precondition(lambda self: bool(self._creditable()))
    @rule(data=st.data())
    def credit_note(self, data: st.DataObject) -> None:
        invoice_id, position = data.draw(st.sampled_from(self._creditable()))
        inv = self.invoices[invoice_id]
        ln = next(x for x in inv.lines if x.position == position)
        left = ln.quantity - credited_quantity(position, inv.credits)
        self.act_credit(invoice_id, position, data.draw(st.integers(1, left)))

    @precondition(lambda self: self.current is not None)
    @rule(
        data=st.data(),
        method=st.sampled_from([PaymentMethod.CASH, PaymentMethod.BANK_TRANSFER, PaymentMethod.QR]),
        aim=st.sampled_from(["oldest", "all", "over", "over", "random"]),
        duplicate=st.booleans(),
        allocate=st.sampled_from([True, True, True, False]),
    )
    def pay(
        self,
        data: st.DataObject,
        method: PaymentMethod,
        aim: str,
        duplicate: bool,
        allocate: bool,
    ) -> None:
        open_invoices = self._open_invoices()
        owed = sum((i.outstanding for i in open_invoices), ZERO)
        if aim == "random" or not open_invoices:
            amount = data.draw(money_st)
        elif aim == "oldest":
            amount = open_invoices[0].outstanding
        elif aim == "all":
            amount = owed
        else:
            amount = owed + data.draw(money_st)
        reference = None
        if duplicate and self.refs and method in REFERENCE_METHODS:
            reference = data.draw(st.sampled_from(sorted(self.refs)))
        self.act_pay(method, amount, allocate=allocate, reference=reference)

    @precondition(lambda self: self.current is not None and self.spendable() > 0)
    @rule(amount=money_st)
    def spend_credit(self, amount: Decimal) -> None:
        self.act_spend_credit(amount)

    @precondition(
        lambda self: any(
            p.method is not PaymentMethod.PATIENT_CREDIT
            and p.verification is not Verification.REJECTED
            for p in self.payments.values()
        )
    )
    @rule(data=st.data())
    def allocate_later(self, data: st.DataObject) -> None:
        options = [
            p.id
            for p in self.payments.values()
            if p.method is not PaymentMethod.PATIENT_CREDIT
            and p.verification is not Verification.REJECTED
        ]
        self.act_allocate_later(data.draw(st.sampled_from(options)))

    @precondition(lambda self: bool(self._live_transfers()))
    @rule(data=st.data(), accept=st.booleans())
    def verify_transfer(self, data: st.DataObject, accept: bool) -> None:
        """Confirm a pending transfer, or reject a pending or confirmed one."""
        pending = [p.id for p in self.payments.values() if p.verification is Verification.PENDING]
        if accept and pending:
            self.act_confirm(data.draw(st.sampled_from(pending)))
        else:
            self.act_reject(data.draw(st.sampled_from([p.id for p in self._live_transfers()])))

    @precondition(
        lambda self: (
            self.current is not None
            and any(cn.created_credit > cn.refunded for cn in self.credit_notes.values())
        )
    )
    @rule(data=st.data())
    def refund(self, data: st.DataObject) -> None:
        options = [c for c in self.credit_notes.values() if c.created_credit > c.refunded]
        cn = data.draw(st.sampled_from(options))
        source = cn.created_credit - cn.refunded
        amount = data.draw(st.decimals(min_value=Decimal("0.01"), max_value=source, places=2))
        self.act_refund(cn.id, amount)

    @precondition(lambda self: bool(self.claims))
    @rule(data=st.data(), share=st.sampled_from([0, 50, 100]), rebill=st.booleans())
    def claim_step(self, data: st.DataObject, share: int, rebill: bool) -> None:
        """Move one claim line along: submit, respond, record a payer payment, or resolve."""
        S = cl.ClaimLineStatus
        options = [
            k
            for k, c in self.claims.items()
            if c.status in (S.ACCRUED, S.CLAIMED, S.ACCEPTED, S.PARTIALLY_ACCEPTED)
            or c.unresolved_rejection > 0
        ]
        if not options:
            return
        key = data.draw(st.sampled_from(sorted(options)))
        line = self.claims[key]
        if line.status is S.ACCRUED:
            self.act_submit_claim(key)
        elif line.status is S.CLAIMED:
            self.act_respond_claim(key, share)
        elif line.unresolved_rejection > 0 and (rebill or line.paid == line.accepted):
            self.act_resolve_rejection(key, rebill=rebill)
        else:
            left = line.accepted - line.paid
            amount = data.draw(st.decimals(min_value=Decimal("0.01"), max_value=left, places=2))
            self.act_payer_payment(key, amount)

    # --- invariants ----------------------------------------------------------------------

    def check_all(self) -> None:
        """Run every invariant (used by the scenario tests after each action)."""
        self.every_journal_balances()
        self.patient_receivable_equals_documents()
        self.payer_receivable_equals_claims()
        self.patient_credit_equals_documents()
        self.payer_share_never_in_cash_or_bank()
        self.settled_lines_are_exactly_the_fully_covered()
        self.allocations_stay_within_payments()
        self.stock_never_negative_and_moves_only_at_dispense()
        self.closed_shifts_never_change()

    @invariant()
    def every_journal_balances(self) -> None:
        for j in self.journals:
            lg.assert_balanced(j)

    @invariant()
    def patient_receivable_equals_documents(self) -> None:
        total = ZERO
        for inv in self.invoices.values():
            outstanding = self.position(inv.id).outstanding
            ledger = lg.account_balance(
                self.journals, lg.Account.AR_PATIENT, patient=PATIENT, invoice=inv.id
            )
            assert ledger == outstanding
            total += outstanding
        assert lg.account_balance(self.journals, lg.Account.AR_PATIENT) == total

    @invariant()
    def payer_receivable_equals_claims(self) -> None:
        for inv in self.invoices.values():
            expected = sum(
                (c.receivable for (iid, _), c in self.claims.items() if iid == inv.id), ZERO
            )
            ledger = lg.account_balance(self.journals, lg.Account.AR_PAYER, invoice=inv.id)
            assert ledger == expected

    @invariant()
    def patient_credit_equals_documents(self) -> None:
        balance = self.credit_balance()
        ledger = lg.account_balance(self.journals, lg.Account.PATIENT_CREDIT, patient=PATIENT)
        assert ledger == balance
        # Credit goes negative only by money that bounced after it had been paid out.
        assert balance >= -self.uncovered
        # Pending money is never spent, refunded or used to cover a bounce: the pool always
        # still holds it, short only by losses already reported as uncovered.
        assert balance - sum(self.pending_unallocated(), ZERO) >= -self.uncovered

    @invariant()
    def payer_share_never_in_cash_or_bank(self) -> None:
        live = [p for p in self.payments.values() if p.verification is not Verification.REJECTED]
        cash = sum((p.amount for p in live if p.method is PaymentMethod.CASH), ZERO)
        pending = sum((p.amount for p in live if p.verification is Verification.PENDING), ZERO)
        confirmed = sum(
            (
                p.amount
                for p in live
                if p.method in REFERENCE_METHODS and p.verification is Verification.CONFIRMED
            ),
            ZERO,
        )
        refunds = sum((r.amount for r in self.refunds), ZERO)
        variances = sum(self.variances, ZERO)
        assert lg.account_balance(self.journals, lg.Account.CASH) == cash - refunds + variances
        assert lg.account_balance(self.journals, lg.Account.BANK_PENDING) == pending
        assert lg.account_balance(self.journals, lg.Account.BANK) == confirmed + self.payer_paid
        no_money = (
            lg.SourceType.INVOICE,
            lg.SourceType.CREDIT_NOTE,
            lg.SourceType.PAYER_REBILL,
            lg.SourceType.PAYER_WRITE_OFF,
            lg.SourceType.ALLOCATION,
        )
        for j in self.journals:
            accounts = {ln.account for ln in j.lines}
            if accounts & lg.MONEY_ACCOUNTS and lg.Account.AR_PAYER in accounts:
                assert j.source_type is lg.SourceType.PAYER_PAYMENT
            if j.source_type in no_money:
                assert not accounts & lg.MONEY_ACCOUNTS

    @invariant()
    def settled_lines_are_exactly_the_fully_covered(self) -> None:
        on_invoice: set[int] = set()
        for inv in self.invoices.values():
            for lp in self.position(inv.id).lines:
                line = self.lines[lp.service_line_id]
                on_invoice.add(line.id)
                if lp.fully_credited:
                    assert line.status.billing is sl.BillingStatus.CREDITED
                else:
                    assert line.status.billing in sl.BILLED
                    assert (line.status.billing is sl.BillingStatus.SETTLED) == lp.settled
        for line in self.lines.values():
            if line.id not in on_invoice:
                assert line.status.billing is sl.BillingStatus.UNBILLED
            if sl.can_enter_worklist(line.status):
                assert line.status.billing is sl.BillingStatus.SETTLED or line.status.authorized

    @invariant()
    def allocations_stay_within_payments(self) -> None:
        records = self._records()
        nets = al.net_by_payment(records)
        for p in self.payments.values():
            net = nets.get(p.id, ZERO)
            assert ZERO <= net <= p.amount
            if p.verification is Verification.REJECTED:
                assert net == 0
        per_pair: dict[tuple[int, int], Decimal] = {}
        for r in records:
            key = (r.payment_id, r.invoice_id)
            per_pair[key] = per_pair.get(key, ZERO) + r.amount
        assert all(v >= 0 for v in per_pair.values())

    @invariant()
    def stock_never_negative_and_moves_only_at_dispense(self) -> None:
        assert all(v >= 0 for v in self.stock.values())
        assert self.stock == sk.on_hand(self.moves)
        dispensed = -sum(m.quantity for m in self.moves if m.kind is sk.MoveKind.DISPENSE)
        assert dispensed == sum(self.dispensed.values())
        for line_id in self.dispensed:
            assert self.lines[line_id].status.fulfilment is sl.FulfilmentStatus.PERFORMED
        assert not any(m.batch_id == 1 and m.kind is sk.MoveKind.DISPENSE for m in self.moves)

    @invariant()
    def closed_shifts_never_change(self) -> None:
        for s in self.shifts.values():
            if s.open:
                continue
            for j in self.journals[s.journal_mark :]:
                assert all(ln.dimensions.get(lg.Dim.SHIFT) != s.id for ln in j.lines)
            assert s.payments_at_close == sum(
                1 for p in self.payments.values() if p.shift_id == s.id
            )
            assert s.refunds_at_close == sum(1 for r in self.refunds if r.shift_id == s.id)


VisitMachine.TestCase.settings = settings(
    stateful_step_count=80,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
TestVisitMachine = VisitMachine.TestCase


# --- deterministic scenarios for paths the random runs reach rarely ----------------------


def _machine(*, allow_partial: bool = False, opening: str = "50000.00") -> VisitMachine:
    m = VisitMachine()
    m.allow_partial = allow_partial
    m.act_open_shift(Decimal(opening))
    return m


def _billing(m: VisitMachine, line_id: int) -> sl.BillingStatus:
    return m.lines[line_id].status.billing


def test_scenario_pay_first_cycle_with_perform_first_exception() -> None:
    m = _machine()
    consult = m.act_order("CONS", 1)
    lab = m.act_order("CBC", 1)
    emergency = m.act_order("INJ", 1)
    assert not m.act_work(lab, "start")  # not paid, not authorized
    assert m.act_authorize(emergency)
    assert m.act_work(emergency, "perform")  # perform-first, documented
    inv = m.act_invoice([consult, lab, emergency])
    assert inv is not None
    m.check_all()
    assert m.position(inv).outstanding == Decimal("9500.00")
    m.act_pay(PaymentMethod.CASH, Decimal("9500.00"))
    m.check_all()
    assert {_billing(m, x) for x in (consult, lab, emergency)} == {sl.BillingStatus.SETTLED}
    assert m.act_work(lab, "start")
    assert m.act_work(lab, "perform")
    m.check_all()


def test_scenario_rejected_confirmed_transfer_claws_back_spent_credit() -> None:
    m = _machine()
    first = m.act_order("CONS", 1)
    inv1 = m.act_invoice([first])
    assert inv1 is not None
    transfer = m.act_pay(PaymentMethod.BANK_TRANSFER, Decimal("8000.00"))
    m.act_confirm(transfer)
    second = m.act_order("CBC", 1)
    inv2 = m.act_invoice([second])
    assert inv2 is not None
    assert m.spendable() == Decimal("3000.00")
    assert m.act_spend_credit(Decimal("3000.00")) is not None
    assert _billing(m, second) is sl.BillingStatus.SETTLED
    m.check_all()
    plan = m.act_reject(transfer)
    assert plan is not None
    assert [d.amount for d in plan.reversals] == [Decimal("-5000.00")]
    assert [d.amount for d in plan.recovery] == [Decimal("-3000.00")]
    assert plan.uncovered == 0
    m.check_all()
    assert m.position(inv1).outstanding == Decimal("5000.00")
    assert m.position(inv2).outstanding == Decimal("3000.00")
    assert _billing(m, first) is sl.BillingStatus.INVOICED
    assert _billing(m, second) is sl.BillingStatus.INVOICED
    assert m.credit_balance() == 0


def test_scenario_refunded_credit_then_bounced_transfer_leaves_the_patient_owing() -> None:
    m = _machine()
    line = m.act_order("CONS", 1)
    inv = m.act_invoice([line])
    assert inv is not None
    transfer = m.act_pay(PaymentMethod.BANK_TRANSFER, Decimal("5000.00"))
    m.act_confirm(transfer)
    cn = m.act_credit(inv, 1, 1)
    assert cn is not None
    assert m.credit_notes[cn].created_credit == Decimal("5000.00")
    assert m.act_refund(cn, Decimal("5000.00"))
    m.check_all()
    plan = m.act_reject(transfer)
    assert plan is not None
    assert plan.uncovered == Decimal("5000.00")
    m.check_all()
    assert m.credit_balance() == Decimal("-5000.00")


def test_scenario_pending_money_is_neither_spent_nor_refunded() -> None:
    m = _machine()
    line = m.act_order("CONS", 1)
    inv = m.act_invoice([line])
    assert inv is not None
    transfer = m.act_pay(PaymentMethod.QR, Decimal("5000.00"))
    assert _billing(m, line) is sl.BillingStatus.SETTLED  # pending money settles the line
    cn = m.act_credit(inv, 1, 1)
    assert cn is not None
    assert m.spendable() == 0
    assert not m.act_refund(cn, Decimal("1.00"))
    m.check_all()
    plan = m.act_reject(transfer)
    assert plan is not None
    assert plan.recovery == ()
    m.check_all()


def test_scenario_bounce_never_uses_pending_money_to_cover_spent_credit() -> None:
    """Regression: a confirmed bounce took pending money as cover, then the pending rejection
    clawed back credit it had never funded (found by the stateful machine)."""
    m = _machine()
    transfer = m.act_pay(PaymentMethod.BANK_TRANSFER, Decimal("3000.00"), allocate=False)
    m.act_confirm(transfer)
    line = m.act_order("CBC", 1)
    inv = m.act_invoice([line])
    assert inv is not None
    pending = m.act_pay(PaymentMethod.QR, Decimal("10.00"), allocate=False)
    assert m.spendable() == Decimal("3000.00")
    assert m.act_spend_credit(Decimal("3000.00")) is not None
    m.check_all()
    # The whole spend is taken back: the pending 10.00 is not confirmed money and must not
    # absorb part of the bounce.
    plan = m.act_reject(transfer)
    assert plan is not None
    assert [d.amount for d in plan.recovery] == [Decimal("-3000.00")]
    assert plan.uncovered == 0
    m.check_all()
    assert m.credit_balance() == Decimal("10.00")
    assert m.spendable() == 0
    assert m.position(inv).outstanding == Decimal("3000.00")
    # Rejecting the pending transfer then touches nothing but its own money.
    plan = m.act_reject(pending)
    assert plan is not None
    assert (plan.reversals, plan.recovery, plan.uncovered) == ((), (), ZERO)
    m.check_all()
    assert m.credit_balance() == 0


def test_scenario_pending_rejection_after_an_uncovered_loss_reports_nothing_new() -> None:
    """A loss already reported stays as it is; rejecting pending money adds no recovery."""
    m = _machine()
    first = m.act_order("CONS", 1)
    inv = m.act_invoice([first])
    assert inv is not None
    transfer = m.act_pay(PaymentMethod.BANK_TRANSFER, Decimal("5000.00"))
    m.act_confirm(transfer)
    cn = m.act_credit(inv, 1, 1)
    assert cn is not None
    assert m.act_refund(cn, Decimal("5000.00"))
    pending = m.act_pay(PaymentMethod.QR, Decimal("200.00"), allocate=False)
    plan = m.act_reject(transfer)
    assert plan is not None
    assert plan.uncovered == Decimal("5000.00")
    m.check_all()
    plan = m.act_reject(pending)
    assert plan is not None
    assert (plan.recovery, plan.uncovered) == ((), ZERO)
    m.check_all()
    assert m.credit_balance() == Decimal("-5000.00")


def test_scenario_later_allocation_is_capped_by_the_credit_pool() -> None:
    m = _machine(allow_partial=True)
    cash = m.act_pay(PaymentMethod.CASH, Decimal("3000.00"), allocate=False)
    line = m.act_order("CONS", 1)
    inv = m.act_invoice([line])
    assert inv is not None
    assert m.act_spend_credit(Decimal("3000.00")) is not None
    assert m.act_allocate_later(cash) == 0  # the pool is empty although the cash shows 3000
    m.check_all()
    assert m.position(inv).outstanding == Decimal("2000.00")


def test_scenario_transfer_rejected_after_shift_close_posts_to_the_new_shift() -> None:
    m = _machine()
    line = m.act_order("CBC", 1)
    inv = m.act_invoice([line])
    assert inv is not None
    transfer = m.act_pay(PaymentMethod.BANK_TRANSFER, Decimal("3000.00"))
    assert m.act_work(line, "start")
    assert m.act_close_shift(ZERO)
    assert m.act_reject(transfer) is None  # no open shift to receive the late effect
    m.check_all()
    m.act_open_shift(Decimal("100.00"))
    assert m.act_reject(transfer) is not None
    m.check_all()
    assert _billing(m, line) is sl.BillingStatus.INVOICED
    assert not m.act_work(line, "perform")  # back off the work list


def test_scenario_partial_dispense_credits_the_rest_and_refunds_it() -> None:
    m = _machine()
    m.act_receive(2, 15)
    m.act_receive(1, 100)  # expired batch: never dispensed
    drug = m.act_order("AMOX", 3)  # 30 tablets
    inv = m.act_invoice([drug])
    assert inv is not None
    m.act_pay(PaymentMethod.CASH, m.position(inv).outstanding)
    assert not m.act_work(drug, "perform")  # only 15 usable tablets
    cn = m.act_credit(inv, 1, 15)
    assert cn is not None
    assert m.lines[drug].status.billing is sl.BillingStatus.SETTLED
    assert m.credit_notes[cn].created_credit == Decimal("1807.50")
    assert m.act_refund(cn, Decimal("1807.50"))
    m.check_all()


def test_scenario_payer_rejection_rebilled_to_the_patient() -> None:
    m = _machine()
    line = m.act_order("CONS", 1, covered=True, rule_index=0)  # 6000 on the payer list, 70%
    inv = m.act_invoice([line])
    assert inv is not None
    key = (inv, 1)
    assert m.claims[key].amount == Decimal("4200.00")
    m.act_pay(PaymentMethod.CASH, Decimal("1800.00"))
    assert _billing(m, line) is sl.BillingStatus.SETTLED
    m.act_submit_claim(key)
    assert m.act_credit(inv, 1, 1) is None  # claimed payer share is locked
    m.act_respond_claim(key, 50)
    m.act_payer_payment(key, Decimal("2100.00"))
    m.act_resolve_rejection(key, rebill=True)
    m.check_all()
    assert m.position(inv).outstanding == Decimal("2100.00")
    assert _billing(m, line) is sl.BillingStatus.INVOICED
    assert m.claims[key].receivable == 0


def test_scenario_credit_note_releases_pending_money_first() -> None:
    m = _machine(allow_partial=True)
    consult = m.act_order("CONS", 1)
    lab = m.act_order("CBC", 1)
    inv = m.act_invoice([consult, lab])
    assert inv is not None
    transfer = m.act_pay(PaymentMethod.QR, Decimal("3000.00"))  # pending, partial payment
    m.act_pay(PaymentMethod.CASH, Decimal("5000.00"))
    assert m.position(inv).outstanding == 0
    cn = m.act_credit(inv, 2, 1)  # the lab test cannot be done
    assert cn is not None
    m.check_all()
    # The excess came off the unverified transfer, so nothing is refundable yet.
    assert m.spendable() == 0
    assert not m.act_refund(cn, Decimal("3000.00"))
    assert _billing(m, consult) is sl.BillingStatus.SETTLED
    m.act_confirm(transfer)
    assert m.act_refund(cn, Decimal("3000.00"))
    m.check_all()
