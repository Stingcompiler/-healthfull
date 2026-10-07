"""Invoices and credit notes: the billing half of the money engine (ARCHITECTURE 4.5).

Every rule comes from ``domain.invoice``, ``domain.coverage`` and ``domain.pricing``; this
module loads rows, locks them, calls the rule, stores the result and posts the ledger.

* A draft invoice is built only from the visit's unbilled, open service lines (no free
  amounts). Draft lines show the prices of today; they are priced again, then frozen, at
  approval from the price list version effective on the approval date (invariant 6).
* Coverage per line: the line's payer, its most specific coverage rule, exclusions, and the
  patient's percent override (``apps.catalog.services.resolve_coverage``). Payer share is
  computed; ``patient_share = gross - discount - payer_share``.
* Discounts touch only the patient share, need a reason, and stay within the approver's role
  limit from ``Policy.discount_limit_percent`` (FEATURES 5.9). A follow-up visit's
  consultation line gets the center's follow-up discount automatically (FEATURES 2.2).
* Approval freezes and numbers the invoice, moves its service lines to invoiced (zero
  patient share settles at once) and posts Dr AR_PATIENT, AR_PAYER, DISCOUNT / Cr REVENUE.
  An approved invoice never changes (invariant 2): corrections are credit notes.
* A credit note credits whole units of invoice lines (cumulative rounding, so all credits
  of a line add up to it exactly). Approval posts the mirror entry, credits the service
  lines (a full credit cancels an open line), de-allocates patient money above the new due
  into patient credit (``apps.payments.services``) and can open a refund request and
  re-bill corrected lines. A payer share already on a claim cannot be credited
  (``CLAIM_LINE_LOCKED``): it is resolved through the claim.

Locks: every operation takes the patient row first (``apps.orders.services.lock_patient``),
then the invoice, then credit notes and service lines.
"""

from __future__ import annotations

import importlib
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from types import ModuleType
from typing import Any

import pghistory
from django.db import transaction
from django.db.models import QuerySet, Sum
from django.utils import timezone

from apps.billing.models import CreditNote, CreditNoteLine, DocumentStatus, Invoice, InvoiceLine
from apps.catalog import services as catalog
from apps.catalog.models import ServiceKind
from apps.claims.models import ClaimLine, ClaimStatus, Resolution
from apps.core.models import Policy, ReasonCode, User
from apps.core.services import next_number, require_permission, resolve_reason
from apps.ledger import services as ledger
from apps.orders import services as orders
from apps.orders.models import BillingStatus, FulfilmentStatus, OrderSource, ServiceLine
from apps.patients.models import Patient
from apps.payments.models import Allocation
from apps.visits.models import Visit, VisitStatus
from domain import coverage as dc
from domain import invoice as di
from domain import ledger as dl
from domain import pricing
from domain import service_line as dsl
from domain.audit import Approval
from domain.errors import DomainError
from domain.money import HUNDRED, ZERO, require_non_negative

__all__ = [
    "apply_discount",
    "apply_invoice_discount",
    "approve_credit_note",
    "approve_invoice",
    "create_credit_note",
    "create_draft_invoice",
    "create_pharmacy_sale",
    "credit_service_line",
    "credited_quantity",
    "drop_from_drafts",
    "invoice_position",
    "open_invoices",
    "refresh_settlement",
    "remove_draft_line",
    "set_preapproval_ref",
    "unbilled_lines",
    "void_draft",
]

#: Kinds a walk-in pharmacy sale may contain (FEATURES 5.12).
SALEABLE_KINDS = frozenset({ServiceKind.DRUG, ServiceKind.CONSUMABLE})


def _payments() -> ModuleType:
    """``apps.payments.services`` (de-allocation, refund requests); imported lazily."""
    return importlib.import_module("apps.payments.services")


def _visits() -> ModuleType:
    """``apps.visits.services`` (pharmacy sale visit, follow-up discount); imported lazily."""
    return importlib.import_module("apps.visits.services")


def _claims() -> ModuleType:
    """``apps.claims.services`` (claimed payer shares); imported lazily."""
    return importlib.import_module("apps.claims.services")


def _patients() -> ModuleType:
    return importlib.import_module("apps.patients.services")


def _acting_shift_id(actor: User) -> int | None:
    """The actor's open shift, read ``FOR SHARE`` so a concurrent close cannot slip between
    choosing the shift and booking into it (invariant 3)."""
    shift_id: int | None = _payments().acting_shift_id(actor)
    return shift_id


def _lock_invoice(invoice: Invoice | int) -> Invoice:
    pk = invoice if isinstance(invoice, int) else invoice.pk
    patient_id = Invoice.objects.filter(pk=pk).values_list("patient_id", flat=True).get()
    orders.lock_patient(patient_id)
    return Invoice.objects.select_for_update(no_key=True).get(pk=pk)


def _require_draft(invoice: Invoice) -> None:
    status = di.InvoiceStatus(invoice.status)
    di.require_editable(status)
    if status is not di.InvoiceStatus.DRAFT:
        raise DomainError("INVOICE_NOT_DRAFT", "The invoice is not a draft", status=str(status))


# --- pricing ---------------------------------------------------------------------------------


@dataclass(slots=True)
class _Pricer:
    """Prices and coverage of draft lines as of one date (one price list read per list)."""

    visit: Visit
    on: date
    versions: dict[int, list[pricing.PriceVersion]]
    approving: bool = False

    def billable(
        self, il: InvoiceLine, sl: ServiceLine, *, enforce_preapproval: bool
    ) -> tuple[di.BillableLine, int | None, str]:
        """The domain input for one line, the coverage rule id and the real pre-approval ref.

        Drafts are priced without enforcing the payer's pre-approval reference (the cashier
        records it on the draft); approval enforces it (FEATURES 5.8).
        """
        payer = sl.payer
        plist = catalog.price_list_for(payer)
        versions = self.versions.get(plist.pk)
        if versions is None:
            version = catalog.effective_version(plist, self.on)
            if self.approving:
                # A concurrent price edit waits for this approval (and is then refused by
                # the version guard), or commits first and is priced here (invariant 6).
                catalog.lock_versions_for_pricing([version.pk])
            prices: dict[pricing.ItemKey, Decimal] = {}
            for service_id, price in catalog.version_prices(version).items():
                prices[service_id] = price
            versions = [pricing.PriceVersion(version.pk, version.effective_from, prices)]
            self.versions[plist.pk] = versions
        rule: dc.CoverageRule | None = None
        rule_id: int | None = None
        excluded = False
        if payer is not None:
            if self.approving:
                dc.require_contract(payer.contract_start, payer.contract_end, self.on)
            cov = self.visit.coverage
            override = (
                cov.patient_percent_override
                if cov is not None and cov.payer_id == payer.pk
                else None
            )
            resolved = catalog.resolve_coverage(
                payer, sl.service, patient_percent_override=override
            )
            rule, excluded = resolved.domain_rule, resolved.excluded
            rule_id = resolved.rule.pk if resolved.rule is not None else None
        ref = (il.pre_approval_ref or sl.pre_approval_ref).strip()
        billable = di.BillableLine(
            service_line_id=sl.pk,
            item=sl.service_id,
            quantity=_bill_quantity(sl),
            status=orders.line_status(sl),
            price_versions=versions,
            payer_id=payer.pk if payer is not None else None,
            coverage=rule,
            excluded=excluded,
            discount=il.discount,
            preapproval_ref=ref or (None if enforce_preapproval else "(draft)"),
        )
        return billable, rule_id, ref


def _bill_quantity(sl: ServiceLine) -> int:
    """Units to bill: the performed quantity of a partly performed line, else the order."""
    if sl.fulfilment_status == FulfilmentStatus.PERFORMED and sl.performed_quantity is not None:
        return orders.whole_quantity(sl.performed_quantity, "performed_quantity")
    return orders.whole_quantity(sl.quantity)


def _lock_service_lines(ids: Iterable[int]) -> dict[int, ServiceLine]:
    rows = (
        ServiceLine.objects.select_for_update(of=("self",))
        .select_related("authorization", "service", "payer")
        .filter(pk__in=list(ids))
        .order_by("id")
    )
    return {sl.pk: sl for sl in rows}


def _price_lines(
    invoice: Invoice,
    lines: Sequence[InvoiceLine],
    service_lines: Mapping[int, ServiceLine],
    on: date,
    *,
    enforce_preapproval: bool = False,
) -> list[di.InvoiceLineDraft]:
    """Price ``lines`` (in order) as of ``on`` and write the amounts onto them (not saved)."""
    visit = Visit.objects.select_related("coverage").get(pk=invoice.visit_id)
    pricer = _Pricer(visit, on, {}, approving=enforce_preapproval)
    billables: list[di.BillableLine] = []
    rule_ids: list[int | None] = []
    refs: list[str] = []
    for il in lines:
        billable, rule_id, ref = pricer.billable(
            il, service_lines[il.service_line_id], enforce_preapproval=enforce_preapproval
        )
        if il.discount_percent is not None:
            billable = replace(billable, discount=ZERO)
        billables.append(billable)
        rule_ids.append(rule_id)
        refs.append(ref)
    if any(il.discount_percent is not None for il in lines):
        # A percent discount is a share of the patient part on the pricing day: derive the
        # amount from that day's price and coverage (FEATURES 5.9, invariant 6).
        bases = di.build_invoice_lines(billables, on)
        billables = [
            replace(b, discount=dc.percent_discount(d.gross - d.payer_share, il.discount_percent))
            if il.discount_percent is not None
            else b
            for il, b, d in zip(lines, billables, bases, strict=True)
        ]
    drafts = di.build_invoice_lines(billables, on)
    for il, billable, d, rule_id, ref in zip(lines, billables, drafts, rule_ids, refs, strict=True):
        il.quantity = Decimal(d.quantity)
        il.unit_price = d.unit_price
        il.gross = d.gross
        il.discount = d.discount
        il.payer_id = d.payer_id
        il.payer_share = d.payer_share
        il.patient_share = d.patient_share
        il.price_list_version_id = d.price_version_id
        il.coverage_rule_id = rule_id
        il.excluded = billable.excluded
        il.pre_approval_ref = ref[:100]
    return list(drafts)


_PRICED_FIELDS = [
    "quantity",
    "unit_price",
    "gross",
    "discount",
    "payer",
    "payer_share",
    "patient_share",
    "price_list_version",
    "coverage_rule",
    "excluded",
    "pre_approval_ref",
]


def _set_totals(doc: Invoice | CreditNote, totals: di.InvoiceTotals) -> None:
    doc.gross_total = totals.gross
    doc.discount_total = totals.discount
    doc.payer_total = totals.payer_share
    doc.patient_total = totals.patient_share


_TOTAL_FIELDS = ["gross_total", "discount_total", "payer_total", "patient_total"]


_DISCOUNT_FIELDS = ["discount_percent", "discount_reason", "discount_note", "discount_approved_by"]


def _reprice_draft(
    invoice: Invoice, on: date | None = None, lines: Sequence[InvoiceLine] | None = None
) -> list[InvoiceLine]:
    """Price every line of a locked draft again; store lines and header totals.

    ``lines`` are the draft's lines with in-memory edits (a new discount); the discount and
    the shares it changes are saved together, so every row stays balanced.
    """
    rows = list(lines) if lines is not None else list(invoice.lines.order_by("line_no"))
    service_lines = _lock_service_lines(il.service_line_id for il in rows)
    drafts = _price_lines(invoice, rows, service_lines, on or timezone.localdate()) if rows else []
    for il in rows:
        il.save(update_fields=[*_PRICED_FIELDS, *_DISCOUNT_FIELDS])
    _set_totals(invoice, di.invoice_totals(drafts))
    invoice.save(update_fields=[*_TOTAL_FIELDS, "updated_at"])
    return rows


# --- drafts ----------------------------------------------------------------------------------


def unbilled_lines(visit: Visit) -> QuerySet[ServiceLine]:
    """The visit's requested lines the cashier can invoice (FLOW step 4)."""
    return (
        ServiceLine.objects.filter(visit=visit, billing_status=BillingStatus.UNBILLED)
        .exclude(fulfilment_status=FulfilmentStatus.CANCELLED)
        .select_related("service")
        .order_by("id")
    )


def _on_open_draft(line_ids: Iterable[int], exclude_invoice: int | None = None) -> list[int]:
    qs = InvoiceLine.objects.filter(
        service_line_id__in=list(line_ids), invoice__status=DocumentStatus.DRAFT
    )
    if exclude_invoice is not None:
        qs = qs.exclude(invoice_id=exclude_invoice)
    return sorted(set(qs.values_list("service_line_id", flat=True)))


def create_draft_invoice(
    visit: Visit,
    actor: User,
    *,
    line_ids: Sequence[int] | None = None,
    on: date | None = None,
) -> Invoice:
    """A draft invoice from the visit's unbilled lines (all of them when ``line_ids`` is None).

    Lines are priced as of ``on`` (default today) for display; approval prices them again.

    Raises:
        DomainError: ``VISIT_CANCELLED``, ``INVOICE_EMPTY``, ``LINE_NOT_ON_VISIT``,
            ``LINE_ON_DRAFT_INVOICE``, ``LINE_NOT_BILLABLE``, ``LINE_CANCELLED``,
            ``NO_EFFECTIVE_PRICE_LIST``, ``PRICE_NOT_FOUND``, ``NO_DEFAULT_PRICE_LIST``.
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="create invoice"):
        orders.lock_patient(visit.patient_id)
        # No visit row lock: visit cancellation locks the visit before the patient, and a line
        # cancelled concurrently leaves every draft anyway (``drop_from_drafts``).
        locked_visit = Visit.objects.get(pk=visit.pk)
        if locked_visit.status == VisitStatus.CANCELLED:
            raise DomainError("VISIT_CANCELLED", "A cancelled visit cannot be invoiced")
        if line_ids is None:
            wanted = list(unbilled_lines(locked_visit).values_list("id", flat=True))
        else:
            wanted = sorted(set(line_ids))
        if not wanted:
            raise DomainError("INVOICE_EMPTY", "There is nothing to invoice")
        service_lines = _lock_service_lines(wanted)
        missing = [i for i in wanted if i not in service_lines]
        if missing or any(sl.visit_id != locked_visit.pk for sl in service_lines.values()):
            raise DomainError(
                "LINE_NOT_ON_VISIT", "The lines must belong to this visit", line_ids=missing
            )
        busy = _on_open_draft(wanted)
        if busy:
            raise DomainError(
                "LINE_ON_DRAFT_INVOICE", "A line is already on a draft invoice", line_ids=busy
            )
        invoice = Invoice.objects.create(
            visit=locked_visit, patient_id=locked_visit.patient_id, created_by=actor
        )
        lines = [
            InvoiceLine(
                invoice=invoice,
                line_no=n,
                service_line=service_lines[sid],
                service=service_lines[sid].service,
                kind=service_lines[sid].kind,
                department_id=service_lines[sid].department_id,
                description_ar=service_lines[sid].service.name_ar[:200],
                description_en=service_lines[sid].service.name_en[:200],
                discount=ZERO,
            )
            for n, sid in enumerate(wanted, start=1)
        ]
        on = on or timezone.localdate()
        drafts = _price_lines(invoice, lines, service_lines, on)
        if _follow_up_discount(locked_visit, lines, drafts, service_lines, actor):
            drafts = _price_lines(invoice, lines, service_lines, on)
        for il in lines:
            il.save()
        _set_totals(invoice, di.invoice_totals(drafts))
        invoice.save(update_fields=[*_TOTAL_FIELDS, "updated_at"])
    return invoice


def _follow_up_discount(
    visit: Visit,
    lines: Sequence[InvoiceLine],
    drafts: Sequence[di.InvoiceLineDraft],
    service_lines: Mapping[int, ServiceLine],
    actor: User,
) -> bool:
    """The center's follow-up discount on the consultation line (FEATURES 2.2, policy rule).

    Set in memory on ``lines``; returns whether any line got one.
    """
    percent = Decimal(_visits().follow_up_discount_percent(visit))
    if not ZERO < percent < HUNDRED:
        return False
    reason = ReasonCode.objects.filter(category="discount", code="FOLLOW_UP", active=True).first()
    if reason is None:
        return False
    applied = False
    for il, d in zip(lines, drafts, strict=True):
        if service_lines[il.service_line_id].order_source != OrderSource.CONSULTATION_FEE:
            continue
        amount = dc.percent_discount(d.gross - d.payer_share, percent)
        if amount > 0:
            # Kept as a percent: approval derives the amount from that day's price.
            il.discount = amount
            il.discount_percent = percent
            il.discount_reason = reason
            il.discount_note = f"follow-up of visit {visit.follow_up_of_id}"
            il.discount_approved_by = actor
            applied = True
    return applied


def remove_draft_line(invoice_line: InvoiceLine, *, actor: User) -> Invoice:
    """Take a line off a draft (it stays requested and can be invoiced later)."""
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="remove invoice line"):
        invoice = _lock_invoice(invoice_line.invoice_id)
        _require_draft(invoice)
        InvoiceLine.objects.filter(pk=invoice_line.pk, invoice=invoice).delete()
        _reprice_draft(invoice)
    return invoice


def drop_from_drafts(line: ServiceLine, *, actor: User) -> None:
    """A cancelled line leaves every draft invoice it was on (caller holds the patient lock)."""
    for invoice_id in (
        InvoiceLine.objects.filter(service_line=line, invoice__status=DocumentStatus.DRAFT)
        .values_list("invoice_id", flat=True)
        .distinct()
    ):
        invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
        InvoiceLine.objects.filter(invoice=invoice, service_line=line).delete()
        remaining = list(invoice.lines.all())
        _set_totals(invoice, _sum_lines(remaining))
        invoice.save(update_fields=[*_TOTAL_FIELDS, "updated_at"])


def _sum_lines(lines: Iterable[InvoiceLine | CreditNoteLine]) -> di.InvoiceTotals:
    gross = discount = payer = patient = ZERO
    for ln in lines:
        gross += ln.gross
        discount += ln.discount
        payer += ln.payer_share
        patient += ln.patient_share
    return di.InvoiceTotals(gross, discount, payer, patient)


def set_preapproval_ref(invoice_line: InvoiceLine, reference: str, *, actor: User) -> InvoiceLine:
    """Record the payer's pre-approval number on a draft line (FEATURES 5.8)."""
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="pre-approval reference"):
        invoice = _lock_invoice(invoice_line.invoice_id)
        _require_draft(invoice)
        il = InvoiceLine.objects.select_for_update().get(pk=invoice_line.pk, invoice=invoice)
        il.pre_approval_ref = reference.strip()[:100]
        il.save(update_fields=["pre_approval_ref"])
        _reprice_draft(invoice)
        il.refresh_from_db()
    return il


def void_draft(invoice: Invoice, *, actor: User, note: str) -> Invoice:
    """Void a draft invoice with a reason (approved invoices take credit notes instead).

    Raises:
        DomainError: ``REASON_REQUIRED``, ``INVOICE_FROZEN``, ``INVOICE_NOT_DRAFT``.
    """
    text = note.strip()
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"void draft: {text}"):
        locked = _lock_invoice(invoice)
        now = timezone.now()
        new = di.void(di.InvoiceStatus(locked.status), Approval(actor.pk, now, text))
        locked.status = str(new)
        locked.voided_by = actor
        locked.voided_at = now
        locked.void_note = text[:500]
        locked.save(update_fields=["status", "voided_by", "voided_at", "void_note", "updated_at"])
    return locked


# --- discounts -------------------------------------------------------------------------------


def _role_limits(approver: User) -> tuple[list[str], dict[str, Decimal]]:
    raw = Policy.load().discount_limit_percent
    limits = {
        str(role): Decimal(str(value))
        for role, value in (raw.items() if isinstance(raw, dict) else [])
        if not isinstance(value, bool)
    }
    roles = approver.role_codes()
    if approver.is_superuser:  # break-glass account (ADR 0004)
        roles = [*roles, "__superuser__"]
        limits["__superuser__"] = HUNDRED
    return roles, limits


def _discount_amount(
    base: Decimal, amount: Decimal | None, percent: Decimal | int | None
) -> tuple[Decimal, Decimal | None]:
    """The discount amount on ``base`` and, for a percent discount, the percent.

    A percent discount is rounded down (``domain.coverage.percent_discount``) so it never
    exceeds the percent, and the percent is kept: approval re-derives the amount from the
    price effective that day.
    """
    if (amount is None) == (percent is None):
        raise DomainError("DISCOUNT_AMOUNT_OR_PERCENT", "Give either an amount or a percent")
    if percent is not None:
        value = dc.percent_discount(base, percent)
        return value, (Decimal(percent) if value > 0 else None)
    return require_non_negative(amount or ZERO, "discount"), None


def _approver(actor: User, approver: User | None) -> User:
    chosen = approver or actor
    if chosen.pk != actor.pk:
        require_permission(chosen, "billing.override_discount_limit")
    return chosen


def apply_discount(
    invoice_line: InvoiceLine,
    *,
    actor: User,
    reason: ReasonCode | str | None,
    amount: Decimal | None = None,
    percent: Decimal | int | None = None,
    note: str = "",
    approver: User | None = None,
) -> InvoiceLine:
    """Discount the patient share of one draft line (FEATURES 5.9, invariant 4).

    The limit is the approver's best role limit (``Policy.discount_limit_percent``) as a
    percentage of the line's patient share before discount. The approver is the actor unless
    a supervisor holding ``billing.override_discount_limit`` approves above the actor's
    limit. A zero amount removes the discount.

    Raises:
        PermissionRequired: a separate approver lacks ``billing.override_discount_limit``.
        DomainError: ``DISCOUNT_AMOUNT_OR_PERCENT``, ``REASON_REQUIRED``, ``REASON_UNKNOWN``,
            ``REASON_NOTE_REQUIRED``, ``DISCOUNT_EXCEEDS_PATIENT_SHARE``,
            ``DISCOUNT_LIMIT_EXCEEDED``, ``INVOICE_FROZEN``, ``INVOICE_NOT_DRAFT``,
            ``INVALID_PERCENT``.
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="discount"):
        invoice = _lock_invoice(invoice_line.invoice_id)
        _require_draft(invoice)
        lines = list(invoice.lines.select_for_update().order_by("line_no"))
        il = next((x for x in lines if x.pk == invoice_line.pk), None)
        if il is None:
            raise InvoiceLine.DoesNotExist(f"invoice line {invoice_line.pk}")
        base = _patient_before_discount(invoice, il)
        value, pct = _discount_amount(base, amount, percent)
        _set_discount([(il, value, base, pct)], actor, reason, note, approver)
        _reprice_draft(invoice, lines=lines)
    return il


def apply_invoice_discount(
    invoice: Invoice,
    *,
    actor: User,
    reason: ReasonCode | str | None,
    amount: Decimal | None = None,
    percent: Decimal | int | None = None,
    note: str = "",
    approver: User | None = None,
) -> Invoice:
    """Spread one discount over a draft's lines in proportion to their patient shares.

    The limit applies to the whole invoice's patient share before discount; the parts add up
    exactly to the discount and none exceeds its line (``domain.coverage``).
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="invoice discount"):
        locked = _lock_invoice(invoice)
        _require_draft(locked)
        lines = list(locked.lines.select_for_update().order_by("line_no"))
        bases = [_patient_before_discount(locked, il) for il in lines]
        total = sum(bases, ZERO)
        chosen = _approver(actor, approver)
        if percent is not None:
            # The same percent on every line (each rounded down): within the limit per line
            # and in total, and re-derived from the day's prices at approval.
            if amount is not None:
                raise DomainError(
                    "DISCOUNT_AMOUNT_OR_PERCENT", "Give either an amount or a percent"
                )
            rows: list[tuple[InvoiceLine, Decimal, Decimal, Decimal | None]] = []
            for il, base in zip(lines, bases, strict=True):
                value, pct = _discount_amount(base, None, percent)
                rows.append((il, value, base, pct))
            _set_discount(rows, actor, reason, note, approver)
            _reprice_draft(locked, lines=lines)
            return locked
        value, _ = _discount_amount(total, amount, None)
        if value > 0:
            reason_obj = resolve_reason(reason, "discount", note)
            roles, limits = _role_limits(chosen)
            dc.check_discount(
                value,
                total,
                roles,
                limits,
                Approval(chosen.pk, timezone.now(), note.strip(), reason_obj.code),
            )
        parts = dc.distribute_discount(value, bases)
        _set_discount(
            [(il, part, base, None) for il, part, base in zip(lines, parts, bases, strict=True)],
            actor,
            reason,
            note,
            approver,
            check=False,
        )
        _reprice_draft(locked, lines=lines)
    return locked


def _patient_before_discount(invoice: Invoice, il: InvoiceLine) -> Decimal:
    """The line's patient share with no discount, at today's prices and coverage."""
    probe = InvoiceLine(
        invoice=invoice,
        line_no=il.line_no,
        service_line_id=il.service_line_id,
        pre_approval_ref=il.pre_approval_ref,
        discount=ZERO,
    )
    service_lines = _lock_service_lines([il.service_line_id])
    (draft,) = _price_lines(invoice, [probe], service_lines, timezone.localdate())
    return draft.gross - draft.payer_share


def _set_discount(
    rows: Sequence[tuple[InvoiceLine, Decimal, Decimal, Decimal | None]],
    actor: User,
    reason: ReasonCode | str | None,
    note: str,
    approver: User | None,
    *,
    check: bool = True,
) -> None:
    """Write ``(line, amount, base, percent)`` discounts; ``percent`` is None for amounts."""
    chosen = _approver(actor, approver)
    reason_obj: ReasonCode | None = None
    if any(value > 0 for _, value, _, _ in rows):
        reason_obj = resolve_reason(reason, "discount", note)
    roles, limits = _role_limits(chosen)
    now = timezone.now()
    for il, value, base, pct in rows:
        if value > 0 and reason_obj is not None:
            if check:
                dc.check_discount(
                    value,
                    base,
                    roles,
                    limits,
                    Approval(chosen.pk, now, note.strip(), reason_obj.code),
                )
            il.discount = value
            il.discount_percent = pct
            il.discount_reason = reason_obj
            il.discount_note = note.strip()[:500]
            il.discount_approved_by = chosen
        else:
            il.discount = ZERO
            il.discount_percent = None
            il.discount_reason = None
            il.discount_note = ""
            il.discount_approved_by = None


def _recheck_discounts(
    lines: Sequence[InvoiceLine], drafts: Sequence[di.InvoiceLineDraft], at: datetime
) -> None:
    """Amount discounts are checked again at approval against the prices of that day.

    Approval prices every line again (invariant 6). A discount given as an amount stays the
    same amount, so a lower price (or a higher payer share) can turn it into a larger share
    of the patient part than its approver may give (FEATURES 5.9, invariant 4). Each
    approver's amount discounts are checked together, as they were given (a line discount or
    an invoice discount spread over lines). Percent discounts are re-derived instead.
    """
    groups: dict[int, tuple[Decimal, Decimal, InvoiceLine]] = {}
    for il, d in zip(lines, drafts, strict=True):
        if d.discount == 0 or il.discount_percent is not None or il.discount_approved_by_id is None:
            continue
        total, base, first = groups.get(il.discount_approved_by_id, (ZERO, ZERO, il))
        groups[il.discount_approved_by_id] = (
            total + d.discount,
            base + d.gross - d.payer_share,
            first,
        )
    for approver_id, (total, base, first) in groups.items():
        approver = User.objects.get(pk=approver_id)
        roles, limits = _role_limits(approver)
        reason_code = first.discount_reason.code if first.discount_reason else ""
        dc.check_discount(
            total, base, roles, limits, Approval(approver_id, at, first.discount_note, reason_code)
        )


# --- approval --------------------------------------------------------------------------------


def _revenue_lines(
    rows: Iterable[tuple[InvoiceLine, Decimal, Decimal, Decimal, Decimal]],
) -> list[dl.RevenueLine]:
    """``(invoice line, gross, discount, payer share, patient share)`` -> ledger revenue lines."""
    return [
        dl.RevenueLine(
            gross=gross,
            discount=discount,
            payer_share=payer,
            patient_share=patient,
            payer_id=il.payer_id,
            department_id=il.department_id or ledger.NO_DEPARTMENT,
            service_kind=il.kind,
        )
        for il, gross, discount, payer, patient in rows
    ]


def approve_invoice(invoice: Invoice, *, actor: User) -> Invoice:
    """Freeze, number and post a draft invoice (invariants 2 and 6, FEATURES 5.4, 5.10).

    Every line is priced again from the version effective today, frozen, and its service
    line moves to invoiced (settled when the patient share is zero).

    Raises:
        DomainError: ``INVOICE_NOT_DRAFT``, ``INVOICE_FROZEN``, ``INVOICE_EMPTY``,
            ``LINE_NOT_BILLABLE``, ``LINE_CANCELLED``, ``NO_EFFECTIVE_PRICE_LIST``,
            ``PRICE_NOT_FOUND``, ``PREAPPROVAL_REQUIRED``, ``DISCOUNT_EXCEEDS_PATIENT_SHARE``,
            ``DISCOUNT_LIMIT_EXCEEDED`` (an amount discount is above its approver's limit at
            the day's prices), ``PAYER_CONTRACT_EXPIRED``.
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="approve invoice"):
        locked = _lock_invoice(invoice)
        new_status = di.approve(di.InvoiceStatus(locked.status))
        today = timezone.localdate()
        now = timezone.now()
        lines = list(locked.lines.order_by("line_no"))
        if not lines:
            raise DomainError("INVOICE_EMPTY", "An invoice needs at least one line")
        service_lines = _lock_service_lines(il.service_line_id for il in lines)
        drafts = _price_lines(locked, lines, service_lines, today, enforce_preapproval=True)
        _recheck_discounts(lines, drafts, now)
        for il in lines:
            il.frozen = True
            il.save(update_fields=[*_PRICED_FIELDS, "frozen"])
        _set_totals(locked, di.invoice_totals(drafts))
        locked.status = str(new_status)
        locked.number = next_number("INV", on=today)
        locked.priced_on = today
        locked.approved_by = actor
        locked.approved_at = now
        locked.save(
            update_fields=[
                *_TOTAL_FIELDS,
                "status",
                "number",
                "priced_on",
                "approved_by",
                "approved_at",
                "updated_at",
            ]
        )
        for il, d in zip(lines, drafts, strict=True):
            orders.apply_invoiced(
                service_lines[il.service_line_id], patient_due=d.patient_share, at=now
            )
        ledger.post(
            dl.post_invoice_approved(
                locked.pk,
                locked.patient_id,
                _revenue_lines(
                    (il, d.gross, d.discount, d.payer_share, d.patient_share)
                    for il, d in zip(lines, drafts, strict=True)
                ),
            ),
            actor=actor,
            shift_id=_acting_shift_id(actor),
        )
    return locked


# --- position --------------------------------------------------------------------------------


def _line_draft(il: InvoiceLine) -> di.InvoiceLineDraft:
    return di.InvoiceLineDraft(
        position=il.line_no,
        service_line_id=il.service_line_id,
        item=il.service_id,
        quantity=orders.whole_quantity(il.quantity),
        unit_price=il.unit_price,
        price_version_id=il.price_list_version_id or 0,
        gross=il.gross,
        discount=il.discount,
        payer_id=il.payer_id,
        payer_share=il.payer_share,
        patient_share=il.patient_share,
        preapproval_ref=il.pre_approval_ref or None,
    )


def _credit_draft(cl: CreditNoteLine, position: int) -> di.CreditLineDraft:
    return di.CreditLineDraft(
        position=position,
        quantity=orders.whole_quantity(cl.quantity),
        gross=cl.gross,
        discount=cl.discount,
        payer_id=cl.invoice_line.payer_id,
        payer_share=cl.payer_share,
        patient_share=cl.patient_share,
    )


def _approved_credits(invoice: Invoice) -> list[di.CreditLineDraft]:
    rows = CreditNoteLine.objects.filter(
        credit_note__invoice=invoice, credit_note__status=DocumentStatus.APPROVED
    ).select_related("invoice_line")
    return [_credit_draft(cl, cl.invoice_line.line_no) for cl in rows]


def invoice_position(invoice: Invoice) -> di.InvoicePosition:
    """Patient position of an approved invoice from its documents (lines in line order).

    Inputs: frozen lines, approved credit note lines, every allocation row (signed), and the
    payer share rebilled to the patient after a payer rejection (claims).
    """
    lines = [_line_draft(il) for il in invoice.lines.filter(frozen=True).order_by("line_no")]
    allocations = list(Allocation.objects.filter(invoice=invoice).values_list("amount", flat=True))
    rebills = [
        di.Rebill(position, amount)
        for position, amount in ClaimLine.objects.filter(
            invoice_line__invoice=invoice, resolution=Resolution.REBILLED
        )
        .exclude(claim__status=ClaimStatus.VOID)
        .values_list("invoice_line__line_no", "rejected_amount")
    ]
    return di.invoice_position(lines, _approved_credits(invoice), allocations, rebills)


def refresh_settlement(invoice: Invoice, *, at: datetime | None = None) -> di.InvoicePosition:
    """Bring each service line of an approved invoice in line with its patient outstanding.

    Called after allocations, reversals, credit notes and rebills (caller holds the patient
    lock). A line is settled exactly when it is not fully credited and owes nothing.
    """
    position = invoice_position(invoice)
    when = at or timezone.now()
    service_lines = _lock_service_lines(lp.service_line_id for lp in position.lines)
    for lp in position.lines:
        orders.sync_settlement(
            service_lines[lp.service_line_id], outstanding=lp.outstanding, at=when
        )
    return position


def open_invoices(patient: Patient) -> list[tuple[Invoice, di.InvoicePosition]]:
    """Approved invoices with patient outstanding, oldest approval first, of every file of
    the person (a merged duplicate's invoices stay payable from the surviving file,
    FEATURES 1.4-1.5)."""
    out = []
    files = _patients().person_file_ids(patient)
    for inv in Invoice.objects.filter(
        patient_id__in=files, status=DocumentStatus.APPROVED
    ).order_by("approved_at", "id"):
        position = invoice_position(inv)
        if position.outstanding > 0:
            out.append((inv, position))
    return out


# --- credit notes ----------------------------------------------------------------------------


def credited_quantity(line: ServiceLine) -> int:
    """Units of the service line taken back by approved credit notes (0 when unbilled).

    Credited units are never given afterwards (invariant 1): work lists, dispensing and
    performance use :func:`domain.service_line.open_quantity` with this count.
    """
    total = CreditNoteLine.objects.filter(
        invoice_line__service_line=line,
        invoice_line__frozen=True,
        credit_note__status=DocumentStatus.APPROVED,
    ).aggregate(t=Sum("quantity"))["t"]
    return orders.whole_quantity(total, "credited") if total else 0


def _lock_invoice_lines(ids: Iterable[int]) -> dict[int, InvoiceLine]:
    """``SELECT ... FOR UPDATE`` the invoice lines (id order) a credit or a claim touches.

    Crediting a payer share and claiming it lock the same invoice line rows, so a claim
    batch and a credit note on one line serialize: the later one sees the earlier one's
    claim line or credit (``CLAIM_LINE_LOCKED`` / a reduced accrued share).
    """
    rows = InvoiceLine.objects.select_for_update().filter(pk__in=list(ids)).order_by("id")
    return {il.pk: il for il in rows}


def _credit_line(
    il: InvoiceLine, sl: ServiceLine, quantity: int, existing: Sequence[di.CreditLineDraft]
) -> di.CreditLineDraft:
    """The domain credit line, refused when it would take back units already given.

    An open line (pending or in progress) may be credited only for units not dispensed yet
    (``CREDIT_EXCEEDS_UNGIVEN``); a performed line is credited financially (a correction).
    """
    credit = di.build_credit_line(_line_draft(il), quantity, existing)
    if sl.fulfilment_status in (FulfilmentStatus.PENDING, FulfilmentStatus.IN_PROGRESS):
        before = di.credited_quantity(il.line_no, existing)
        dsl.open_quantity(
            orders.whole_quantity(il.quantity),
            credited=before + quantity,
            given=orders.given_units(sl),
        )
    return credit


def _claim_of(il: InvoiceLine, payer_credit: Decimal) -> ClaimLine | None:
    """The live claim line holding the payer share a credit takes back, if it may be
    withdrawn for it (``domain.claims.withdraw_for_credit``); ``CLAIM_LINE_LOCKED`` else."""
    if payer_credit <= 0:
        return None
    claimed: ClaimLine | None = _claims().claim_line_for_credit(il, payer_credit)
    return claimed


def create_credit_note(
    invoice: Invoice,
    lines: Sequence[tuple[InvoiceLine | int, Decimal | int]],
    *,
    actor: User,
    reason: ReasonCode | str | None,
    note: str = "",
) -> CreditNote:
    """A draft credit note crediting whole units of approved invoice lines (FEATURES 5.11).

    Raises:
        DomainError: ``INVOICE_NOT_APPROVED``, ``INVOICE_EMPTY``, ``DUPLICATE_LINE``,
            ``UNKNOWN_INVOICE_LINE``, ``INVALID_QUANTITY``, ``CREDIT_EXCEEDS_LINE``,
            ``CREDIT_EXCEEDS_UNGIVEN``, ``CLAIM_LINE_LOCKED``, reason errors.
    """
    reason_obj = resolve_reason(reason, "credit_note", note)
    if not lines:
        raise DomainError("INVOICE_EMPTY", "Choose the lines to credit")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="credit note"):
        locked = _lock_invoice(invoice)
        if locked.status != DocumentStatus.APPROVED:
            raise DomainError("INVOICE_NOT_APPROVED", "Only an approved invoice can be credited")
        ids = [x if isinstance(x, int) else x.pk for x, _ in lines]
        if len(set(ids)) != len(ids):
            raise DomainError("DUPLICATE_LINE", "Credit each invoice line once per note")
        by_id = {
            pk: il for pk, il in _lock_invoice_lines(ids).items() if il.invoice_id == locked.pk
        }
        service_lines = _lock_service_lines(il.service_line_id for il in by_id.values())
        existing = _approved_credits(locked)
        drafts: list[tuple[InvoiceLine, di.CreditLineDraft]] = []
        for line_id, qty in zip(ids, (q for _, q in lines), strict=True):
            il = by_id.get(line_id)
            if il is None or not il.frozen:
                raise DomainError(
                    "UNKNOWN_INVOICE_LINE", "The line is not on this invoice", line_id=line_id
                )
            credit = _credit_line(
                il, service_lines[il.service_line_id], orders.whole_quantity(qty), existing
            )
            _claim_of(il, credit.payer_share)
            drafts.append((il, credit))
        cn = CreditNote.objects.create(
            invoice=locked,
            patient_id=locked.patient_id,
            reason_code=reason_obj,
            reason_note=note.strip(),
            created_by=actor,
        )
        for n, (il, c) in enumerate(drafts, start=1):
            CreditNoteLine.objects.create(
                credit_note=cn,
                line_no=n,
                invoice_line=il,
                quantity=Decimal(c.quantity),
                gross=c.gross,
                discount=c.discount,
                payer_share=c.payer_share,
                patient_share=c.patient_share,
            )
        _set_totals(cn, di.invoice_totals(c for _, c in drafts))
        cn.save(update_fields=[*_TOTAL_FIELDS, "updated_at"])
    return cn


@dataclass(frozen=True, slots=True)
class CreditOutcome:
    """What approving a credit note did besides freezing it."""

    credit_note: CreditNote
    deallocated: Decimal
    replacements: tuple[ServiceLine, ...]
    refund: Any | None


def approve_credit_note(
    credit_note: CreditNote,
    *,
    actor: User,
    line_cancel_reason: ReasonCode | None = None,
    cancel_note: str = "",
    rebill: bool = False,
    open_refund: bool = False,
    service_line: ServiceLine | None = None,
    refund_requested_by: User | None = None,
) -> CreditOutcome:
    """Approve, freeze, number and post a credit note (invariant 2, FEATURES 5.11).

    * Only a holder of ``billing.approve_credit_note`` approves (invariant 4).
    * Mirror ledger entry against the original invoice's receivables. A claimed payer share
      it takes back has its claim line withdrawn (``domain.claims.withdraw_for_credit``).
    * Fully credited service lines become credited; open ones are also cancelled with
      ``line_cancel_reason`` (default: line-cancel reason ``OTHER`` citing this note).
    * The patient money the credited lines held above their new due is de-allocated into
      patient credit (``domain.invoice.credit_release``): it never drifts onto the
      invoice's other lines (ARCHITECTURE 4.4 rule 3).
    * ``rebill`` creates a replacement line for each fully credited line (a correction).
    * ``open_refund`` opens a refund request for the de-allocated money (FLOW 8), requested
      by ``refund_requested_by`` (default the approver).

    Raises:
        PermissionRequired: the actor lacks ``billing.approve_credit_note``.
        DomainError: ``INVOICE_NOT_DRAFT`` (the note is not a draft), ``CREDIT_EXCEEDS_LINE``,
            ``CREDIT_EXCEEDS_UNGIVEN``, ``CLAIM_LINE_LOCKED``.
    """
    require_permission(actor, "billing.approve_credit_note")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="approve credit note"):
        cn_row = CreditNote.objects.only("invoice_id").get(pk=credit_note.pk)
        invoice = _lock_invoice(cn_row.invoice_id)
        cn = (
            CreditNote.objects.select_for_update(of=("self",))
            .select_related("reason_code")
            .get(pk=credit_note.pk)
        )
        new_status = di.approve(di.InvoiceStatus(cn.status))
        now = timezone.now()
        today = timezone.localdate()
        cn_lines = list(cn.lines.order_by("line_no"))
        invoice_lines = _lock_invoice_lines(cl.invoice_line_id for cl in cn_lines)
        service_lines = _lock_service_lines(il.service_line_id for il in invoice_lines.values())
        before = invoice_position(invoice)
        existing = _approved_credits(invoice)
        credited_after: dict[int, int] = defaultdict(int)
        for c in existing:
            credited_after[c.position] += c.quantity
        drafts: list[di.CreditLineDraft] = []
        claims_to_withdraw: list[tuple[ClaimLine, Decimal]] = []
        for cl in cn_lines:
            il = invoice_lines[cl.invoice_line_id]
            c = _credit_line(
                il,
                service_lines[il.service_line_id],
                orders.whole_quantity(cl.quantity),
                existing,
            )
            claimed = _claim_of(il, c.payer_share)
            if claimed is not None:
                claims_to_withdraw.append((claimed, c.payer_share))
            existing = [*existing, c]
            credited_after[il.line_no] += c.quantity
            drafts.append(c)
        for cl, c in zip(cn_lines, drafts, strict=True):
            il = invoice_lines[cl.invoice_line_id]
            fully = credited_after[il.line_no] == orders.whole_quantity(il.quantity)
            sl = service_lines[il.service_line_id]
            cl.gross, cl.discount = c.gross, c.discount
            cl.payer_share, cl.patient_share = c.payer_share, c.patient_share
            cl.cancels_service_line = fully and sl.fulfilment_status in (
                FulfilmentStatus.PENDING,
                FulfilmentStatus.IN_PROGRESS,
            )
            cl.frozen = True
            cl.save(
                update_fields=[
                    "gross",
                    "discount",
                    "payer_share",
                    "patient_share",
                    "cancels_service_line",
                    "frozen",
                ]
            )
        _set_totals(cn, di.invoice_totals(drafts))
        cn.status = str(new_status)
        cn.number = next_number("CN", on=today)
        cn.approved_by = actor
        cn.approved_at = now
        cn.save(
            update_fields=[
                *_TOTAL_FIELDS,
                "status",
                "number",
                "approved_by",
                "approved_at",
                "updated_at",
            ]
        )
        for claimed, payer_credit in claims_to_withdraw:
            _claims().withdraw_for_credit(
                claimed, credit=payer_credit, actor=actor, note=f"credit note {cn.number}"
            )
        ledger.post(
            dl.post_credit_note(
                cn.pk,
                invoice.pk,
                invoice.patient_id,
                _revenue_lines(
                    (
                        invoice_lines[cl.invoice_line_id],
                        c.gross,
                        c.discount,
                        c.payer_share,
                        c.patient_share,
                    )
                    for cl, c in zip(cn_lines, drafts, strict=True)
                ),
            ),
            actor=actor,
            shift_id=_acting_shift_id(actor),
        )

        reason_text = cancel_note.strip() or cn.reason_note or cn.reason_code.code
        approval = Approval(actor.pk, now, reason_text, cn.reason_code.code)
        cancel_reason = line_cancel_reason or resolve_reason(
            "OTHER", "line_cancel", note=f"credit note {cn.number}"
        )
        replacements: list[ServiceLine] = []
        for cl in cn_lines:
            il = invoice_lines[cl.invoice_line_id]
            sl = service_lines[il.service_line_id]
            fully = credited_after[il.line_no] == orders.whole_quantity(il.quantity)
            if sl.billing_status == BillingStatus.CREDITED:
                continue
            orders.apply_credit(
                sl,
                approval=approval,
                fully_credited=fully,
                actor=actor,
                cancel_reason=cancel_reason,
                cancel_note=cancel_note or f"credit note {cn.number}",
            )
            if fully and rebill:
                replacements.append(orders.create_replacement(sl, approval=approval, actor=actor))

        after = invoice_position(invoice)
        release = max(di.credit_release(before, after), after.over_allocation)
        deallocated = ZERO
        if release > 0:
            deallocated = _payments().deallocate_for_credit_note(invoice, cn, release, actor=actor)
        refresh_settlement(invoice, at=now)
        refund = None
        if open_refund and deallocated > 0:
            refunds = _payments().open_refunds_for_credit_note(
                cn,
                requested_by=refund_requested_by or actor,
                reason="SERVICE_CANCELLED",
                note=cancel_note,
                service_line=service_line,
            )
            refund = refunds[0] if refunds else None
    return CreditOutcome(cn, deallocated, tuple(replacements), refund)


def credit_service_line(
    line: ServiceLine,
    *,
    actor: User,
    line_reason: ReasonCode,
    note: str = "",
    quantity: int | None = None,
    open_refund: bool = True,
    approver: User | None = None,
) -> CreditOutcome:
    """Credit a billed service line (all remaining units, or ``quantity``) in one step.

    Used by line cancellation (FLOW 4-6): a credit note with reason ``SERVICE_CANCELLED`` is
    created by the actor and approved by ``approver`` (default the actor), who must hold
    ``billing.approve_credit_note``; its patient money becomes refundable credit, with the
    refund requested by the actor.
    """
    il = (
        InvoiceLine.objects.filter(service_line=line, frozen=True).select_related("invoice").first()
    )
    if il is None:
        raise DomainError("LINE_NOT_CREDITABLE", "The line is not on an approved invoice")
    if quantity is None:
        remaining = orders.whole_quantity(il.quantity) - credited_quantity(line)
        quantity = orders.whole_quantity(remaining, "remaining")
    text = f"{line_reason.code}: {note.strip()}".strip(": ")
    cn = create_credit_note(
        il.invoice, [(il, quantity)], actor=actor, reason="SERVICE_CANCELLED", note=text
    )
    return approve_credit_note(
        cn,
        actor=approver or actor,
        line_cancel_reason=line_reason,
        cancel_note=note,
        open_refund=open_refund,
        service_line=line,
        refund_requested_by=actor,
    )


# --- walk-in pharmacy sale -------------------------------------------------------------------


def create_pharmacy_sale(
    patient: Patient,
    items: Sequence[orders.LineInput | Mapping[str, Any]],
    *,
    actor: User,
) -> Invoice:
    """A standalone pharmacy invoice for a walk-in customer, same rules (FEATURES 5.12).

    Opens a ``pharmacy_sale`` visit without coverage, orders the drug and consumable lines
    and returns their draft invoice. The cashier approves and collects it as any other; the
    pharmacy dispenses the settled lines.

    Raises:
        DomainError: ``SERVICE_NOT_SALEABLE`` and the errors of visit creation, ordering and
            :func:`create_draft_invoice`.
    """
    inputs = [i if isinstance(i, orders.LineInput) else orders.LineInput(**i) for i in items]
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="pharmacy sale"):
        from apps.catalog.models import Service

        ids = [i.service if isinstance(i.service, int) else i.service.pk for i in inputs]
        kinds = dict(Service.objects.filter(pk__in=ids).values_list("id", "kind"))
        bad = sorted(i for i in ids if kinds.get(i) not in SALEABLE_KINDS)
        if bad:
            raise DomainError(
                "SERVICE_NOT_SALEABLE", "Only drugs and consumables are sold", service_ids=bad
            )
        visit = _visits().create_visit(
            patient=patient, actor=actor, visit_type="pharmacy_sale", use_default_coverage=False
        )
        lines = orders.create_service_lines(
            visit,
            [
                orders.LineInput(
                    service=i.service,
                    quantity=i.quantity,
                    order_source=OrderSource.PHARMACY_SALE,
                    note=i.note,
                )
                for i in inputs
            ],
            actor,
        )
        return create_draft_invoice(visit, actor, line_ids=[ln.pk for ln in lines])
