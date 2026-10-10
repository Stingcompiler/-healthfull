"""Payer claims: batches, responses, rejections, payer payments, receivables (FEATURES 11).

Invariant 7: the payer share of an approved invoice line is a receivable (AR_PAYER) until a
payer payment is recorded. Its life (``domain.claims``):

``accrued`` (on an approved invoice, not yet claimed) -> ``claimed`` (a ``ClaimLine`` of a
claim batch) -> ``accepted`` / ``rejected`` / ``partially_accepted`` -> ``paid``; a rejected
part is rebilled to the patient or written off, once, with a reason and approver.

* Accrued amount of an invoice line = payer share minus payer share credited by approved
  credit notes (credits are refused once the line is claimed: ``CLAIM_LINE_LOCKED``).
* Ledger postings go through ``apps.ledger.services.post``: rebill Dr AR_PATIENT /
  Cr AR_PAYER (the patient's due on the invoice grows and its lines' settlement is
  refreshed), write-off Dr WRITE_OFF / Cr AR_PAYER, payer payment Dr BANK (transfer),
  BANK_PENDING (cheque, until it clears) or CASH (the recording cashier's open shift) /
  Cr AR_PAYER.
* A payer payment is allocated in full to accepted, unpaid claim-line amounts (the chart has
  no payer advance account); without explicit allocations it pays the oldest claims first
  (``domain.claims.allocate_oldest_first``). A bounced transfer or cheque is reversed with
  negative allocation rows; an accepted amount the payer short-pays is written off with an
  approval (FEATURES 11.5-11.7).
* A credit note that takes back a claimed payer share withdraws its claim line
  (``domain.claims.withdraw_for_credit``); building a claim and crediting a line lock the
  same invoice line rows, so they never both take one payer share.
* :func:`payer_receivables` derives the AR_PAYER balance from the documents; it always equals
  the ledger (tested).

DB status mapping: ``pending`` = claimed (on a draft or submitted batch, awaiting the payer);
``partial`` = partially accepted; ``withdrawn`` = taken off a draft or void batch. ``paid``
is derived from the payer payment allocations.
"""

from __future__ import annotations

import importlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from types import ModuleType

import pghistory
from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q, Sum
from django.utils import timezone

from apps.billing.models import CreditNoteLine, DocumentStatus, InvoiceLine
from apps.catalog.models import Payer
from apps.claims.models import (
    Claim,
    ClaimLine,
    ClaimLineStatus,
    ClaimStatus,
    PayerPayment,
    PayerPaymentAllocation,
    PayerPaymentMethod,
    Resolution,
)
from apps.core.models import Policy, User
from apps.core.services import holds_permission, next_number, require_permission, resolve_reason
from apps.ledger import services as ledger
from apps.payments.models import Bank, Shift, ShiftStatus
from domain import claims as dclaims
from domain import ledger as dl
from domain.audit import Approval
from domain.errors import DomainError
from domain.money import ZERO, require_positive

__all__ = [
    "AGING_BUCKETS",
    "AccruedLine",
    "ClaimResponse",
    "PayerReceivable",
    "accrued_lines",
    "build_claim",
    "claim_line_for_credit",
    "claim_line_state",
    "clear_payer_cheque",
    "close_claim",
    "payer_aging",
    "payer_receivables",
    "record_payer_payment",
    "record_responses",
    "remove_claim_line",
    "resolve_rejection",
    "reverse_payer_payment",
    "submit_claim",
    "void_claim",
    "withdraw_for_credit",
    "write_off_shortfall",
]

#: Aging buckets in days since invoice approval (``domain.claims``).
AGING_BUCKETS = dclaims.AGING_BUCKETS

_DB_STATUS = {
    dclaims.ClaimLineStatus.ACCEPTED: ClaimLineStatus.ACCEPTED,
    dclaims.ClaimLineStatus.REJECTED: ClaimLineStatus.REJECTED,
    dclaims.ClaimLineStatus.PARTIALLY_ACCEPTED: ClaimLineStatus.PARTIAL,
}


def _billing() -> ModuleType:
    return importlib.import_module("apps.billing.services")


def _orders() -> ModuleType:
    return importlib.import_module("apps.orders.services")


def _live_claim_line() -> Q:
    """Claim lines that hold the invoice line's payer share (not withdrawn, batch not void)."""
    return ~Q(status=ClaimLineStatus.WITHDRAWN) & ~Q(claim__status=ClaimStatus.VOID)


# --- state mapping --------------------------------------------------------------------------


def _paid(claim_line: ClaimLine) -> Decimal:
    total = PayerPaymentAllocation.objects.filter(claim_line=claim_line).aggregate(t=Sum("amount"))[
        "t"
    ]
    return total or ZERO


def claim_line_state(claim_line: ClaimLine, *, paid: Decimal | None = None) -> dclaims.ClaimLine:
    """The domain view of a stored claim line (amounts and status checked on construction)."""
    paid_amount = _paid(claim_line) if paid is None else paid
    off = claim_line.written_off_amount
    st = claim_line.status
    resolution = (
        dclaims.Resolution(claim_line.resolution)
        if claim_line.resolution != Resolution.NONE
        else None
    )
    amount = claim_line.amount_claimed
    if st == ClaimLineStatus.WITHDRAWN:
        return dclaims.ClaimLine(dclaims.ClaimLineStatus.VOIDED, ZERO)
    if st == ClaimLineStatus.PENDING:
        return dclaims.ClaimLine(dclaims.ClaimLineStatus.CLAIMED, amount)
    accepted = claim_line.accepted_amount
    if st == ClaimLineStatus.REJECTED:
        status = {
            None: dclaims.ClaimLineStatus.REJECTED,
            dclaims.Resolution.REBILLED: dclaims.ClaimLineStatus.REBILLED,
            dclaims.Resolution.WRITTEN_OFF: dclaims.ClaimLineStatus.WRITTEN_OFF,
        }[resolution]
        return dclaims.ClaimLine(status, amount, resolution=resolution)
    if paid_amount == accepted and accepted > 0 and off == 0:
        return dclaims.ClaimLine(
            dclaims.ClaimLineStatus.PAID, amount, accepted, paid_amount, resolution
        )
    status = (
        dclaims.ClaimLineStatus.ACCEPTED
        if st == ClaimLineStatus.ACCEPTED
        else dclaims.ClaimLineStatus.PARTIALLY_ACCEPTED
    )
    return dclaims.ClaimLine(status, amount, accepted, paid_amount, resolution, written_off=off)


# --- accrued payer shares and claim batches -------------------------------------------------


@dataclass(frozen=True, slots=True)
class AccruedLine:
    """The unclaimed payer share of one approved invoice line."""

    invoice_line: InvoiceLine
    amount: Decimal
    approved_on: date


def _credited_payer(invoice_line_ids: Sequence[int]) -> dict[int, Decimal]:
    rows = (
        CreditNoteLine.objects.filter(
            invoice_line_id__in=list(invoice_line_ids),
            credit_note__status=DocumentStatus.APPROVED,
        )
        .values("invoice_line_id")
        .annotate(t=Sum("payer_share"))
    )
    return {r["invoice_line_id"]: r["t"] or ZERO for r in rows}


def _accrued(il: InvoiceLine, credited: Decimal) -> Decimal:
    line = dclaims.accrue(il.payer_share)
    if credited > 0:
        line = dclaims.reduce_for_credit(line, credited)
    return line.amount


def accrued_lines(
    payer: Payer,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
) -> list[AccruedLine]:
    """Unclaimed payer shares of approved invoices (by approval date), oldest first."""
    claimed = ClaimLine.objects.filter(_live_claim_line(), invoice_line_id=OuterRef("pk"))
    qs = (
        InvoiceLine.objects.filter(
            payer=payer,
            frozen=True,
            invoice__status=DocumentStatus.APPROVED,
            payer_share__gt=0,
        )
        .exclude(Exists(claimed))
        .select_related("invoice")
        .order_by("invoice__priced_on", "invoice_id", "line_no")
    )
    if period_start is not None:
        qs = qs.filter(invoice__priced_on__gte=period_start)
    if period_end is not None:
        qs = qs.filter(invoice__priced_on__lte=period_end)
    lines = list(qs)
    credited = _credited_payer([il.pk for il in lines])
    out = []
    for il in lines:
        amount = _accrued(il, credited.get(il.pk, ZERO))
        approved_on = il.invoice.priced_on or timezone.localdate(il.invoice.approved_at)
        if amount > 0:
            out.append(AccruedLine(il, amount, approved_on))
    return out


def _refresh_totals(claim: Claim) -> None:
    sums = ClaimLine.objects.filter(claim=claim).exclude(status=ClaimLineStatus.WITHDRAWN)
    agg = sums.aggregate(
        c=Sum("amount_claimed"), a=Sum("accepted_amount"), r=Sum("rejected_amount")
    )
    claim.claimed_total = agg["c"] or ZERO
    claim.accepted_total = agg["a"] or ZERO
    claim.rejected_total = agg["r"] or ZERO


def build_claim(
    *,
    payer: Payer,
    period_start: date,
    period_end: date,
    actor: User,
    invoice_line_ids: Sequence[int] | None = None,
    note: str = "",
) -> Claim:
    """A draft claim batch of the payer's accrued shares in the period (FEATURES 11.3).

    Raises:
        DomainError: ``INVALID_DATE_RANGE``, ``CLAIM_EMPTY``, ``CLAIM_LINE_NOT_ACCRUED``
            (a chosen invoice line is not an unclaimed payer share of this payer and period).
    """
    if period_end < period_start:
        raise DomainError("INVALID_DATE_RANGE", "The period ends before it starts")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="build claim"):
        # One batch at a time per payer, so an invoice line cannot enter two claims.
        Payer.objects.select_for_update(no_key=True).get(pk=payer.pk)
        candidates = accrued_lines(payer, period_start=period_start, period_end=period_end)
        # Lock the candidate invoice lines (id order), as crediting a payer share does, then
        # read the accrued shares again: a credit note approved meanwhile is seen here, and
        # one approved later finds the claim line (it withdraws it or is refused).
        list(
            InvoiceLine.objects.select_for_update()
            .filter(pk__in=[a.invoice_line.pk for a in candidates])
            .order_by("id")
            .values_list("id", flat=True)
        )
        lines = accrued_lines(payer, period_start=period_start, period_end=period_end)
        if invoice_line_ids is not None:
            wanted = set(invoice_line_ids)
            available = {a.invoice_line.pk for a in lines}
            missing = sorted(wanted - available)
            if missing:
                raise DomainError(
                    "CLAIM_LINE_NOT_ACCRUED",
                    "Some lines are not unclaimed payer shares of this payer and period",
                    invoice_line_ids=missing,
                )
            lines = [a for a in lines if a.invoice_line.pk in wanted]
        if not lines:
            raise DomainError("CLAIM_EMPTY", "Nothing to claim for this payer and period")
        claim = Claim.objects.create(
            number=next_number("CLM"),
            payer=payer,
            period_start=period_start,
            period_end=period_end,
            note=note,
            created_by=actor,
        )
        ClaimLine.objects.bulk_create(
            [
                ClaimLine(claim=claim, invoice_line=a.invoice_line, amount_claimed=a.amount)
                for a in lines
            ]
        )
        _refresh_totals(claim)
        claim.save(update_fields=["claimed_total", "accepted_total", "rejected_total"])
    return claim


def _withdraw(line: ClaimLine, actor: User, note: str) -> None:
    line.status = ClaimLineStatus.WITHDRAWN
    line.withdrawn_at = timezone.now()
    line.withdrawn_by = actor
    line.withdraw_note = note.strip()[:500] or "withdrawn"
    line.save(update_fields=["status", "withdrawn_at", "withdrawn_by", "withdraw_note"])


def claim_line_for_credit(invoice_line: InvoiceLine, payer_credit: Decimal) -> ClaimLine | None:
    """The live claim line a credit of ``payer_credit`` on ``invoice_line`` must withdraw.

    None when the payer share is not claimed. Raises ``CLAIM_LINE_LOCKED`` when the line
    cannot be withdrawn for that credit (``domain.claims.withdraw_for_credit``). The caller
    holds the invoice line lock (``apps.billing.services``).
    """
    claimed = ClaimLine.objects.filter(_live_claim_line(), invoice_line=invoice_line).first()
    if claimed is None:
        return None
    dclaims.withdraw_for_credit(claim_line_state(claimed), payer_credit)
    return claimed


def withdraw_for_credit(claim_line: ClaimLine, *, credit: Decimal, actor: User, note: str) -> Claim:
    """Withdraw a claim line whose payer share an approved credit note took back.

    The claim, then the line, are locked (the order every claim service uses) and the rule
    is checked again on the locked line. The claim's totals no longer count it; whatever
    payer share is left on the invoice line is claimable again in a later batch.

    Raises:
        DomainError: ``CLAIM_LINE_LOCKED`` (the payer answered or paid meanwhile).
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"withdraw: {note}"):
        claim = Claim.objects.select_for_update().get(pk=claim_line.claim_id)
        locked = ClaimLine.objects.select_for_update().get(pk=claim_line.pk)
        dclaims.withdraw_for_credit(claim_line_state(locked), credit)
        _withdraw(locked, actor, note)
        _refresh_totals(claim)
        claim.save(update_fields=["claimed_total", "accepted_total", "rejected_total"])
    return claim


def _lock_claim(claim: Claim, *statuses: str) -> Claim:
    locked = Claim.objects.select_for_update().get(pk=claim.pk)
    if locked.status not in statuses:
        raise DomainError(
            "CLAIM_STATUS_INVALID", "Not allowed in this claim status", status=locked.status
        )
    return locked


def remove_claim_line(claim_line: ClaimLine, *, actor: User) -> Claim:
    """Take a line off a draft batch; its payer share is accrued (claimable) again."""
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="remove claim line"):
        claim = _lock_claim(claim_line.claim, ClaimStatus.DRAFT)
        locked = ClaimLine.objects.select_for_update().get(pk=claim_line.pk, claim=claim)
        if locked.status != ClaimLineStatus.PENDING:
            raise DomainError("CLAIM_LINE_NOT_CLAIMED", "Only a pending line can be removed")
        _withdraw(locked, actor, "removed from the draft batch")
        _refresh_totals(claim)
        claim.save(update_fields=["claimed_total", "accepted_total", "rejected_total"])
    return claim


def submit_claim(claim: Claim, *, actor: User) -> Claim:
    """The batch was sent to the payer (exported as Excel/PDF)."""
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="submit claim"):
        locked = _lock_claim(claim, ClaimStatus.DRAFT)
        if not locked.lines.filter(status=ClaimLineStatus.PENDING).exists():
            raise DomainError("CLAIM_EMPTY", "The claim has no lines")
        locked.status = ClaimStatus.SUBMITTED
        locked.submitted_by = actor
        locked.submitted_at = timezone.now()
        locked.save(update_fields=["status", "submitted_by", "submitted_at", "updated_at"])
    return locked


def void_claim(claim: Claim, *, actor: User, note: str) -> Claim:
    """Void a batch the payer never answered; its lines become claimable again."""
    if not note.strip():
        raise DomainError("REASON_REQUIRED", "Voiding a claim needs a reason")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"void claim: {note}"):
        locked = _lock_claim(claim, ClaimStatus.DRAFT, ClaimStatus.SUBMITTED)
        if locked.lines.exclude(
            status__in=[ClaimLineStatus.PENDING, ClaimLineStatus.WITHDRAWN]
        ).exists():
            raise DomainError("CLAIM_HAS_RESPONSES", "A claim with responses cannot be voided")
        for line in locked.lines.select_for_update().filter(status=ClaimLineStatus.PENDING):
            _withdraw(line, actor, f"claim voided: {note.strip()}")
        locked.status = ClaimStatus.VOID
        locked.note = f"{locked.note}\n{note.strip()}".strip()
        locked.save(update_fields=["status", "note", "updated_at"])
    return locked


@dataclass(frozen=True, slots=True)
class ClaimResponse:
    """The payer's answer for one claim line: the accepted amount (the rest is rejected)."""

    claim_line_id: int
    accepted: Decimal
    reason: str = ""
    reference: str = ""


def record_responses(claim: Claim, responses: Sequence[ClaimResponse], *, actor: User) -> Claim:
    """Record the payer's per-line answers (FEATURES 11.4). A rejected part needs the
    payer's reason.

    Raises:
        DomainError: ``CLAIM_STATUS_INVALID``, ``CLAIM_LINE_UNKNOWN``,
            ``CLAIM_LINE_NOT_CLAIMED`` (already answered), ``CLAIM_AMOUNT_INVALID``,
            ``REASON_REQUIRED``, ``DUPLICATE_LINE``.
    """
    if not responses:
        raise DomainError("CLAIM_EMPTY", "No responses given")
    ids = [r.claim_line_id for r in responses]
    if len(set(ids)) != len(ids):
        raise DomainError("DUPLICATE_LINE", "A claim line appears twice")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="claim response"):
        locked = _lock_claim(claim, ClaimStatus.SUBMITTED, ClaimStatus.RESPONDED)
        lines = {
            cl.pk: cl
            for cl in ClaimLine.objects.select_for_update().filter(claim=locked, pk__in=ids)
        }
        now = timezone.now()
        for resp in responses:
            cl = lines.get(resp.claim_line_id)
            if cl is None or cl.status == ClaimLineStatus.WITHDRAWN:
                raise DomainError(
                    "CLAIM_LINE_UNKNOWN", "Unknown claim line", claim_line_id=resp.claim_line_id
                )
            answered = dclaims.respond(claim_line_state(cl), resp.accepted, reason=resp.reason)
            cl.status = _DB_STATUS[answered.status]
            cl.accepted_amount = answered.accepted
            cl.rejected_amount = answered.rejected
            cl.payer_reason = resp.reason.strip()[:300]
            cl.payer_reference = resp.reference.strip()[:100]
            cl.responded_at = now
            cl.responded_by = actor
            cl.save(
                update_fields=[
                    "status",
                    "accepted_amount",
                    "rejected_amount",
                    "payer_reason",
                    "payer_reference",
                    "responded_at",
                    "responded_by",
                ]
            )
        _refresh_totals(locked)
        locked.status = ClaimStatus.RESPONDED
        locked.response_at = now
        locked.save(
            update_fields=[
                "claimed_total",
                "accepted_total",
                "rejected_total",
                "status",
                "response_at",
                "updated_at",
            ]
        )
    return locked


def _resolution_approval(
    actor: User, approver: User | None, *, at: datetime, note: str, reason_code: str
) -> tuple[Approval, User | None]:
    """The approval of a rebill or write-off and the second person to record, if any.

    ``Policy.claims_second_approver`` (default on, ADR 0018) requires someone other than the
    recording user, holding ``claims.resolve_rejection``; off, the recorder approves alone
    (ADR 0012).
    """
    second = Policy.load().claims_second_approver
    approval = dclaims.resolution_approval(
        second_person=second,
        actor_id=actor.pk,
        approver_id=None if approver is None else approver.pk,
        at=at,
        reason=note,
        reason_code=reason_code,
    )
    if not second:
        return approval, None
    if approver is None or not holds_permission(approver, "claims.resolve_rejection"):
        raise DomainError(
            "APPROVER_NOT_PERMITTED",
            "The approver may not approve this action",
            permission="claims.resolve_rejection",
        )
    return approval, approver


def resolve_rejection(
    claim_line: ClaimLine,
    *,
    resolution: str,
    actor: User,
    reason_code: str,
    note: str = "",
    approver: User | None = None,
) -> ClaimLine:
    """Rebill the rejected part to the patient or write it off (FEATURES 11.5, invariant 4).

    Rebill: Dr AR_PATIENT / Cr AR_PAYER on the original invoice; the patient now owes it
    and the invoice's line settlement is refreshed. Write-off: Dr WRITE_OFF / Cr AR_PAYER.
    A second person (``approver``) approves while ``Policy.claims_second_approver`` is on.

    Raises:
        PermissionDenied: without ``claims.resolve_rejection``.
        DomainError: ``CLAIM_NOTHING_REJECTED``, ``INVALID_RESOLUTION``,
            ``SECOND_APPROVER_REQUIRED``, ``APPROVER_NOT_PERMITTED``, reason errors.
    """
    require_permission(actor, "claims.resolve_rejection")
    if resolution not in (Resolution.REBILLED, Resolution.WRITTEN_OFF):
        raise DomainError("INVALID_RESOLUTION", "Rebill or write off", resolution=resolution)
    reason = resolve_reason(reason_code, "writeoff", note)
    il = InvoiceLine.objects.select_related("invoice").get(pk=claim_line.invoice_line_id)
    invoice = il.invoice
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"{resolution}: {note}"):
        if resolution == Resolution.REBILLED:
            _orders().lock_patient(invoice.patient_id)
        locked = ClaimLine.objects.select_for_update().get(pk=claim_line.pk)
        now = timezone.now()
        approval, second = _resolution_approval(
            actor, approver, at=now, note=note, reason_code=reason.code
        )
        dclaims.resolve_rejection(
            claim_line_state(locked), dclaims.Resolution(resolution), approval
        )
        locked.resolution = resolution
        locked.resolution_reason = reason
        locked.resolution_note = note.strip()
        locked.resolved_by = actor
        locked.resolution_approved_by = second
        locked.resolved_at = now
        locked.save(
            update_fields=[
                "resolution",
                "resolution_reason",
                "resolution_note",
                "resolved_by",
                "resolution_approved_by",
                "resolved_at",
            ]
        )
        payer_id = il.payer_id or locked.claim.payer_id
        if resolution == Resolution.REBILLED:
            draft = dl.post_payer_rebill(
                locked.pk, invoice.patient_id, payer_id, invoice.pk, locked.rejected_amount
            )
        else:
            draft = dl.post_payer_write_off(locked.pk, payer_id, invoice.pk, locked.rejected_amount)
        ledger.post(draft, actor=actor)
        if resolution == Resolution.REBILLED:
            _billing().refresh_settlement(invoice, at=now)
    return locked


def close_claim(claim: Claim, *, actor: User) -> Claim:
    """Close a batch once every line is paid or resolved (nothing left to collect)."""
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="close claim"):
        locked = _lock_claim(claim, ClaimStatus.RESPONDED)
        open_lines = [
            cl.pk
            for cl in locked.lines.exclude(status=ClaimLineStatus.WITHDRAWN)
            if not dclaims.is_settled(claim_line_state(cl))
        ]
        if open_lines:
            raise DomainError(
                "CLAIM_NOT_SETTLED", "Some lines are unpaid or unresolved", claim_lines=open_lines
            )
        locked.status = ClaimStatus.CLOSED
        locked.closed_at = timezone.now()
        locked.save(update_fields=["status", "closed_at", "updated_at"])
    return locked


# --- payer payments -------------------------------------------------------------------------


def _auto_allocation(payer: Payer, amount: Decimal) -> dict[int, Decimal]:
    """Oldest claims first (``domain.claims.allocate_oldest_first``)."""
    lines = (
        ClaimLine.objects.filter(
            claim__payer=payer,
            status__in=[ClaimLineStatus.ACCEPTED, ClaimLineStatus.PARTIAL],
        )
        .exclude(claim__status=ClaimStatus.VOID)
        .order_by("claim__period_end", "claim_id", "id")
    )
    return dclaims.allocate_oldest_first(
        amount, ((cl.pk, claim_line_state(cl).unpaid) for cl in lines)
    )


def _claim_allocation(payer: Payer, claim_amounts: Mapping[int, Decimal]) -> dict[int, Decimal]:
    """Each claim's amount over its own accepted, unpaid lines in line order (the caller
    holds the payer lock; the lines are locked and checked again by the caller)."""
    lines = (
        ClaimLine.objects.filter(
            claim__payer=payer,
            claim_id__in=list(claim_amounts),
            status__in=[ClaimLineStatus.ACCEPTED, ClaimLineStatus.PARTIAL],
        )
        .exclude(claim__status=ClaimStatus.VOID)
        .order_by("claim_id", "id")
    )
    dues: dict[int, list[tuple[int, Decimal]]] = defaultdict(list)
    for cl in lines:
        dues[cl.claim_id].append((cl.pk, claim_line_state(cl).unpaid))
    return dclaims.allocate_to_claims(claim_amounts, dues)


_MONEY = {
    PayerPaymentMethod.BANK_TRANSFER: dl.PayerMoney.BANK,
    PayerPaymentMethod.CHEQUE: dl.PayerMoney.CHEQUE,
    PayerPaymentMethod.CASH: dl.PayerMoney.CASH,
}


def record_payer_payment(
    *,
    payer: Payer,
    amount: Decimal,
    received_on: date,
    actor: User,
    method: str = PayerPaymentMethod.BANK_TRANSFER,
    bank: Bank | None = None,
    reference: str = "",
    allocations: Mapping[int, Decimal] | None = None,
    claim_amounts: Mapping[int, Decimal] | None = None,
    note: str = "",
) -> PayerPayment:
    """Money received from a payer, allocated to accepted claim lines (FEATURES 11.6).

    ``allocations`` name claim lines; ``claim_amounts`` name claim batches (what the payer's
    remittance advice paid per claim), each spread over that claim's accepted, unpaid lines,
    oldest first (``domain.claims.allocate_to_claims``); give one or the other
    (``PAYER_ALLOCATION_CONFLICT``). With neither, the payment pays accepted amounts of the
    oldest claims first.
    The allocations must equal the payment. Where the money lands depends on the method:
    a bank transfer Dr BANK; a cheque Dr BANK_PENDING until :func:`clear_payer_cheque`; cash
    Dr CASH in the recording user's open shift (it is counted in that drawer) / Cr AR_PAYER.

    Raises:
        DomainError: ``INVALID_AMOUNT``, ``INVALID_PAYMENT_METHOD``, ``BANK_REQUIRED``,
            ``REFERENCE_REQUIRED``, ``DUPLICATE_REFERENCE``, ``CLAIM_LINE_UNKNOWN``,
            ``CLAIM_LINE_NOT_ACCEPTED``, ``CLAIM_PAYMENT_EXCEEDS_ACCEPTED``,
            ``PAYER_PAYMENT_UNBALANCED``, ``SHIFT_NOT_OPEN`` (cash without an open shift),
            ``CLAIM_NOTHING_UNPAID`` (a claim with nothing accepted left unpaid),
            ``PAYER_ALLOCATION_CONFLICT`` (both lines and claims named).
    """
    total = require_positive(amount, "amount")
    if allocations is not None and claim_amounts is not None:
        raise DomainError(
            "PAYER_ALLOCATION_CONFLICT", "Allocate to claim lines or to claims, not both"
        )
    if method not in PayerPaymentMethod.values:
        raise DomainError("INVALID_PAYMENT_METHOD", "Unknown payment method", method=method)
    if method == PayerPaymentMethod.BANK_TRANSFER:
        if bank is None:
            raise DomainError("BANK_REQUIRED", "A transfer names the bank")
        if not reference.strip():
            raise DomainError("REFERENCE_REQUIRED", "A transfer has a reference")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="payer payment"):
        shift_id: int | None = None
        if method == PayerPaymentMethod.CASH:
            shift = (
                Shift.objects.select_for_update()
                .filter(cashier=actor, status=ShiftStatus.OPEN)
                .first()
            )
            if shift is None:
                raise DomainError("SHIFT_NOT_OPEN", "Payer cash goes into your open shift")
            shift_id = shift.pk
        Payer.objects.select_for_update(no_key=True).get(pk=payer.pk)
        if allocations is not None:
            wanted = dict(allocations)
        elif claim_amounts is not None:
            wanted = _claim_allocation(payer, claim_amounts)
        else:
            wanted = _auto_allocation(payer, total)
        lines = {
            cl.pk: cl
            for cl in ClaimLine.objects.select_for_update()
            .filter(pk__in=list(wanted), claim__payer=payer)
            .exclude(claim__status=ClaimStatus.VOID)
            .select_related("invoice_line")
        }
        states = {pk: claim_line_state(cl) for pk, cl in lines.items()}
        dclaims.validate_payer_payment(total, wanted, states)
        try:
            with transaction.atomic():
                payment = PayerPayment.objects.create(
                    number=next_number("PP"),
                    payer=payer,
                    amount=total,
                    method=method,
                    bank=bank,
                    reference=reference.strip(),
                    received_on=received_on,
                    shift_id=shift_id,
                    note=note,
                    recorded_by=actor,
                )
        except IntegrityError as exc:
            if "claims_payerpayment_reference_unique" in str(exc):
                raise DomainError(
                    "DUPLICATE_REFERENCE", "This bank reference was already recorded"
                ) from exc
            raise
        per_invoice: dict[int, Decimal] = defaultdict(lambda: ZERO)
        for pk, value in sorted(wanted.items()):
            cl = lines[pk]
            PayerPaymentAllocation.objects.create(
                payer_payment=payment,
                claim_id=cl.claim_id,
                claim_line=cl,
                amount=value,
                created_by=actor,
            )
            per_invoice[cl.invoice_line.invoice_id] += value
        ledger.post(
            dl.post_payer_payment(
                payment.pk,
                payer.pk,
                sorted(per_invoice.items()),
                money=_MONEY[PayerPaymentMethod(method)],
                shift_id=shift_id,
            ),
            actor=actor,
            entry_date=received_on,
            shift_id=shift_id,
        )
    return payment


def clear_payer_cheque(payment: PayerPayment, *, actor: User, note: str = "") -> PayerPayment:
    """A payer cheque cleared at the bank: Dr BANK / Cr BANK_PENDING (FEATURES 11.6).

    Raises:
        PermissionRequired: without ``claims.record_payer_payment``.
        DomainError: ``PAYMENT_NOT_PENDING`` (not a cheque, already cleared or reversed).
    """
    require_permission(actor, "claims.record_payer_payment")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"cheque cleared {note}"):
        locked = PayerPayment.objects.select_for_update().get(pk=payment.pk)
        if (
            locked.method != PayerPaymentMethod.CHEQUE
            or locked.cleared_at is not None
            or locked.reversed_at is not None
        ):
            raise DomainError("PAYMENT_NOT_PENDING", "Only an uncleared cheque can clear")
        locked.cleared_at = timezone.now()
        locked.cleared_by = actor
        locked.save(update_fields=["cleared_at", "cleared_by"])
        ledger.post(dl.post_payer_cheque_cleared(locked.pk, locked.amount), actor=actor)
    return locked


def reverse_payer_payment(payment: PayerPayment, *, actor: User, note: str) -> PayerPayment:
    """A payer transfer or cheque that bounced or was recorded in error (FEATURES 11.6).

    Its allocations are reversed with negative rows (the claim lines owe again) and the
    ledger posting is undone from where the money sits now (BANK, or BANK_PENDING for an
    uncleared cheque). Payer cash is counted money and is never reversed.

    Raises:
        PermissionRequired: without ``claims.record_payer_payment``.
        DomainError: ``REASON_REQUIRED``, ``PAYMENT_NOT_REVERSIBLE`` (cash, or already
            reversed), ``CLAIM_FINAL`` (a claim it paid is closed).
    """
    require_permission(actor, "claims.record_payer_payment")
    text = note.strip()
    if not text:
        raise DomainError("REASON_REQUIRED", "Say why the payer payment is reversed")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"reverse: {text}"):
        locked = PayerPayment.objects.select_for_update().get(pk=payment.pk)
        Payer.objects.select_for_update(no_key=True).get(pk=locked.payer_id)
        if locked.method == PayerPaymentMethod.CASH or locked.reversed_at is not None:
            raise DomainError(
                "PAYMENT_NOT_REVERSIBLE", "Only an unreversed transfer or cheque is reversed"
            )
        rows = list(
            locked.allocations.filter(reversal_of__isnull=True)
            .select_related("claim", "claim_line__invoice_line")
            .order_by("id")
        )
        if any(r.claim.status == ClaimStatus.CLOSED for r in rows):
            raise DomainError("CLAIM_FINAL", "A claim this payment paid is closed")
        per_invoice: dict[int, Decimal] = defaultdict(lambda: ZERO)
        for row in rows:
            PayerPaymentAllocation.objects.create(
                payer_payment=locked,
                claim_id=row.claim_id,
                claim_line_id=row.claim_line_id,
                amount=-row.amount,
                reversal_of=row,
                created_by=actor,
            )
            if row.claim_line is not None:
                per_invoice[row.claim_line.invoice_line.invoice_id] += row.amount
        money = (
            dl.PayerMoney.CHEQUE
            if locked.method == PayerPaymentMethod.CHEQUE and locked.cleared_at is None
            else dl.PayerMoney.BANK
        )
        locked.reversed_at = timezone.now()
        locked.reversed_by = actor
        locked.reverse_note = text
        locked.save(update_fields=["reversed_at", "reversed_by", "reverse_note"])
        ledger.post(
            dl.post_payer_payment_reversed(
                locked.pk, locked.payer_id, sorted(per_invoice.items()), money=money
            ),
            actor=actor,
        )
    return locked


def write_off_shortfall(
    claim_line: ClaimLine,
    amount: Decimal,
    *,
    actor: User,
    reason_code: str,
    note: str = "",
    approver: User | None = None,
) -> ClaimLine:
    """Write off accepted money the payer will not pay (withholding, deductions; FEATURES
    11.5-11.7): Dr WRITE_OFF / Cr AR_PAYER, with reason, approver and time (invariant 4).
    A second person (``approver``) approves while ``Policy.claims_second_approver`` is on.

    Raises:
        PermissionRequired: without ``claims.resolve_rejection``.
        DomainError: ``CLAIM_NOTHING_UNPAID``, ``CLAIM_AMOUNT_INVALID``, ``INVALID_AMOUNT``,
            ``SECOND_APPROVER_REQUIRED``, ``APPROVER_NOT_PERMITTED``, reason errors.
    """
    require_permission(actor, "claims.resolve_rejection")
    reason = resolve_reason(reason_code, "writeoff", note)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"short pay: {note}"):
        claim = Claim.objects.select_for_update().get(pk=claim_line.claim_id)
        locked = (
            ClaimLine.objects.select_for_update(of=("self",))
            .select_related("invoice_line")
            .get(pk=claim_line.pk)
        )
        now = timezone.now()
        approval, second = _resolution_approval(
            actor, approver, at=now, note=note, reason_code=reason.code
        )
        after = dclaims.write_off_shortfall(claim_line_state(locked), amount, approval)
        locked.written_off_amount = after.written_off
        locked.written_off_reason = reason
        locked.written_off_note = note.strip()
        locked.written_off_by = actor
        locked.written_off_approved_by = second
        locked.written_off_at = now
        locked.save(
            update_fields=[
                "written_off_amount",
                "written_off_reason",
                "written_off_note",
                "written_off_by",
                "written_off_approved_by",
                "written_off_at",
            ]
        )
        ledger.post(
            dl.post_payer_short_write_off(
                locked.pk, claim.payer_id, locked.invoice_line.invoice_id, amount
            ),
            actor=actor,
        )
    return locked


# --- receivables and aging ------------------------------------------------------------------


@dataclass(slots=True)
class PayerReceivable:
    """A payer's share by stage (FEATURES 11.7, 12.7). ``receivable`` = AR_PAYER balance."""

    payer_id: int
    accrued: Decimal = ZERO
    claimed: Decimal = ZERO
    accepted_unpaid: Decimal = ZERO
    rejected_unresolved: Decimal = ZERO
    collected: Decimal = ZERO
    rebilled: Decimal = ZERO
    written_off: Decimal = ZERO
    aging: dict[str, Decimal] = field(default_factory=dict)

    @property
    def receivable(self) -> Decimal:
        return self.accrued + self.claimed + self.accepted_unpaid + self.rejected_unresolved


def _bucket(age_days: int) -> str:
    return dclaims.aging_bucket(age_days)


def payer_receivables(
    *, payer: Payer | None = None, as_of: date | None = None
) -> dict[int, PayerReceivable]:
    """Per payer: what is accrued, claimed, accepted but unpaid, rejected but unresolved,
    collected, rebilled and written off, with the outstanding receivable aged by invoice
    approval date. Never counts payer share as collected before a payer payment.
    """
    today = as_of or timezone.localdate()
    out: dict[int, PayerReceivable] = {}

    def row(pid: int) -> PayerReceivable:
        if pid not in out:
            out[pid] = PayerReceivable(pid, aging={name: ZERO for name, _ in AGING_BUCKETS})
        return out[pid]

    payers = Payer.objects.filter(pk=payer.pk) if payer is not None else Payer.objects.all()
    for p in payers:
        for acc in accrued_lines(p):
            r = row(p.pk)
            r.accrued += acc.amount
            r.aging[_bucket((today - acc.approved_on).days)] += acc.amount

    claim_lines = ClaimLine.objects.filter(_live_claim_line()).select_related(
        "claim", "invoice_line__invoice"
    )
    if payer is not None:
        claim_lines = claim_lines.filter(claim__payer=payer)
    paid = dict(
        PayerPaymentAllocation.objects.filter(claim_line__in=claim_lines)
        .values("claim_line_id")
        .annotate(t=Sum("amount"))
        .values_list("claim_line_id", "t")
    )
    for cl in claim_lines:
        state = claim_line_state(cl, paid=paid.get(cl.pk, ZERO))
        r = row(cl.claim.payer_id)
        r.collected += state.paid
        if state.status is dclaims.ClaimLineStatus.CLAIMED:
            r.claimed += state.amount
        else:
            r.accepted_unpaid += state.unpaid
            r.rejected_unresolved += state.unresolved_rejection
            r.written_off += state.written_off
            if state.resolution is dclaims.Resolution.REBILLED:
                r.rebilled += state.rejected
            elif state.resolution is dclaims.Resolution.WRITTEN_OFF:
                r.written_off += state.rejected
        if state.receivable > 0:
            approved_on = cl.invoice_line.invoice.priced_on or today
            r.aging[_bucket((today - approved_on).days)] += state.receivable
    return out


def payer_aging(*, as_of: date | None = None) -> dict[int, dict[str, Decimal]]:
    """Outstanding payer receivable per payer and age bucket (FEATURES 11.7)."""
    return {pid: r.aging for pid, r in payer_receivables(as_of=as_of).items()}
