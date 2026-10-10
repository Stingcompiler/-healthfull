"""The accountant's claim commands (FLOW step 10, FEATURES 11.3-11.6).

Each command runs one ``apps.claims.services`` operation and returns what the screen shows
next (``apps.claims.queries``), so a router makes one call. Rules, locks, ledger postings and
audit context stay in the services and ``domain.claims``; this module only resolves the
request's references (a claim line must belong to the claim in the path) and turns the
screen's answers into the service's inputs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from apps.catalog.models import Payer
from apps.claims import queries
from apps.claims import services as cs
from apps.claims.models import Claim, ClaimLine, ClaimLineStatus, PayerPayment
from apps.core.models import User
from apps.payments.approvals import ApproverLogin, resolve_approver
from apps.payments.models import Bank
from domain import claims as dclaims
from domain.errors import DomainError

__all__ = [
    "build_claim",
    "clear_cheque",
    "close_claim",
    "record_payer_payment",
    "record_responses",
    "remove_line",
    "resolve_rejection",
    "reverse_payer_payment",
    "submit_claim",
    "void_claim",
    "write_off_shortfall",
]


def _line_of(claim_id: int, line_id: int) -> ClaimLine:
    """Claim line ``line_id`` of claim ``claim_id`` (404 when it belongs to another claim)."""
    return ClaimLine.objects.get(pk=line_id, claim_id=claim_id)


def build_claim(
    *,
    payer_id: int,
    period_start: date,
    period_end: date,
    invoice_line_ids: Sequence[int] | None,
    note: str,
    actor: User,
) -> dict[str, Any]:
    """A draft claim of the payer's accrued shares in the period (all, or the chosen lines)."""
    claim = cs.build_claim(
        payer=Payer.objects.get(pk=payer_id),
        period_start=period_start,
        period_end=period_end,
        actor=actor,
        invoice_line_ids=invoice_line_ids,
        note=note.strip(),
    )
    return queries.claim_detail(claim.pk)


def remove_line(claim_id: int, line_id: int, *, actor: User) -> dict[str, Any]:
    """Take a line off a draft claim; its payer share is claimable again."""
    cs.remove_claim_line(_line_of(claim_id, line_id), actor=actor)
    return queries.claim_detail(claim_id)


def submit_claim(claim_id: int, *, actor: User) -> dict[str, Any]:
    """The batch was sent to the payer."""
    cs.submit_claim(Claim.objects.get(pk=claim_id), actor=actor)
    return queries.claim_detail(claim_id)


def void_claim(claim_id: int, *, actor: User, note: str) -> dict[str, Any]:
    """Void a batch the payer never answered; its lines are claimable again."""
    cs.void_claim(Claim.objects.get(pk=claim_id), actor=actor, note=note)
    return queries.claim_detail(claim_id)


def close_claim(claim_id: int, *, actor: User) -> dict[str, Any]:
    """Close a batch once nothing is left to collect or resolve."""
    cs.close_claim(Claim.objects.get(pk=claim_id), actor=actor)
    return queries.claim_detail(claim_id)


def record_responses(
    claim_id: int, answers: Sequence[Mapping[str, Any]], *, actor: User
) -> dict[str, Any]:
    """The payer's per-line answers: ``accepted`` (all), ``rejected`` (nothing) or
    ``partial`` (the accepted part), each with the payer's reason and reference
    (``domain.claims.response_amount``; the service checks the rest under its locks)."""
    claim = Claim.objects.get(pk=claim_id)
    ids = [int(a["claim_line_id"]) for a in answers]
    claimed = dict(
        ClaimLine.objects.filter(claim=claim, pk__in=ids)
        .exclude(status=ClaimLineStatus.WITHDRAWN)
        .values_list("pk", "amount_claimed")
    )
    responses = []
    for answer in answers:
        line_id = int(answer["claim_line_id"])
        if line_id not in claimed:
            raise DomainError("CLAIM_LINE_UNKNOWN", "Unknown claim line", claim_line_id=line_id)
        accepted = dclaims.response_amount(
            str(answer["outcome"]), claimed[line_id], answer.get("accepted")
        )
        responses.append(
            cs.ClaimResponse(
                line_id,
                accepted,
                reason=str(answer.get("reason") or ""),
                reference=str(answer.get("reference") or ""),
            )
        )
    cs.record_responses(claim, responses, actor=actor)
    return queries.claim_detail(claim_id)


def resolve_rejection(
    claim_id: int,
    line_id: int,
    *,
    actor: User,
    resolution: str,
    reason: str,
    note: str,
    approver: ApproverLogin | None = None,
) -> dict[str, Any]:
    """Rebill the rejected part to the patient or write it off, with a reason (11.5); a
    second person types their credentials while the policy asks for one (ADR 0018)."""
    cs.resolve_rejection(
        _line_of(claim_id, line_id),
        resolution=resolution,
        actor=actor,
        reason_code=reason,
        note=note,
        approver=resolve_approver(approver, actor=actor),
    )
    return queries.claim_detail(claim_id)


def write_off_shortfall(
    claim_id: int,
    line_id: int,
    *,
    actor: User,
    amount: Decimal,
    reason: str,
    note: str,
    approver: ApproverLogin | None = None,
) -> dict[str, Any]:
    """Write off accepted money the payer will not pay, with a reason (11.5); a second person
    approves while the policy asks for one (ADR 0018)."""
    cs.write_off_shortfall(
        _line_of(claim_id, line_id),
        amount,
        actor=actor,
        reason_code=reason,
        note=note,
        approver=resolve_approver(approver, actor=actor),
    )
    return queries.claim_detail(claim_id)


def record_payer_payment(
    *,
    payer_id: int,
    amount: Decimal,
    method: str,
    bank_id: int | None,
    reference: str,
    received_on: date,
    claims: Sequence[tuple[int, Decimal]] | None,
    lines: Sequence[tuple[int, Decimal]] | None,
    note: str,
    actor: User,
) -> dict[str, Any]:
    """Money received from a payer, allocated per claim, per claim line, or (neither given)
    to the oldest claims first (11.6)."""
    payment = cs.record_payer_payment(
        payer=Payer.objects.get(pk=payer_id),
        amount=amount,
        received_on=received_on,
        actor=actor,
        method=method,
        bank=Bank.objects.get(pk=bank_id) if bank_id is not None else None,
        reference=reference,
        allocations=_once(lines),
        claim_amounts=_once(claims),
        note=note.strip(),
    )
    return queries.payer_payment(payment.pk)


def _once(rows: Sequence[tuple[int, Decimal]] | None) -> dict[int, Decimal] | None:
    """Allocation rows by target; a target named twice is refused (``DUPLICATE_LINE``)."""
    if rows is None:
        return None
    out: dict[int, Decimal] = {}
    for target, value in rows:
        if target in out:
            raise DomainError("DUPLICATE_LINE", "An allocation target appears twice", id=target)
        out[target] = value
    return out


def clear_cheque(payment_id: int, *, actor: User, note: str) -> dict[str, Any]:
    """A payer cheque cleared at the bank."""
    cs.clear_payer_cheque(PayerPayment.objects.get(pk=payment_id), actor=actor, note=note)
    return queries.payer_payment(payment_id)


def reverse_payer_payment(payment_id: int, *, actor: User, note: str) -> dict[str, Any]:
    """A payer transfer or cheque that bounced: its allocations are reversed."""
    cs.reverse_payer_payment(PayerPayment.objects.get(pk=payment_id), actor=actor, note=note)
    return queries.payer_payment(payment_id)
