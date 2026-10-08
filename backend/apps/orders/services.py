"""The service line write path (ARCHITECTURE 4.4, FEATURES 4; invariants 1 and 4).

Every status change of a ``ServiceLine`` goes through this module, which asks
``domain.service_line`` for the transition and then stores it with its actor and time:

* Ordering: :func:`create_service_lines` adds ``requested`` lines (unbilled, pending) to an
  open visit; the payer is the visit's.
* Work: :func:`start_line` and :func:`perform_line` need eligibility (settled, or an unrevoked
  perform-first authorization). :func:`worklist` lists exactly the eligible lines.
* Perform-first: :func:`authorize_perform_first` records who allowed it and why (FEATURES 4.4);
  :func:`revoke_authorization` withdraws it for lines that have not started. An inpatient
  stay is its own documented exception (:func:`authorize_stay`): bed nights are performed
  first and billed in arrears (:func:`order_performed`).
* Quantities: units an approved credit note took back are never given, so what may still be
  performed is ``domain.service_line.open_quantity`` of the ordered, credited and given
  (dispensed) units (invariant 1).
* Cancelling: an unbilled line is cancelled (and dropped from draft invoices); an invoiced or
  settled line is credited by a credit note issued through ``apps.billing.services`` and
  approved by a holder of ``billing.approve_credit_note`` (the actor, or a named approver);
  the patient money on it becomes patient credit with a refund request opened (FLOW 5, 8).
  A line with dispensed units is never cancelled outright: the given units are performed
  and only the rest is closed by :func:`cancel_line_remainder` (partial dispense, FEATURES
  8.3).
* Payer: :func:`set_line_payer` moves an unbilled line to another payer of the patient (or to
  cash), so one invoice can carry several payers (FEATURES 5.6).

``apply_invoiced``, ``sync_settlement``, ``apply_credit`` and ``create_replacement`` are the
billing engine's entry points into line statuses; they expect the caller to hold the
patient lock (see ``apps.payments.services`` for the lock order).

Routers check the permission of the action itself. Services check only permissions that are
part of the rule (authorizing perform-first).
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import ModuleType
from typing import Any

import pghistory
from django.db import connection, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.catalog.models import Service, ServiceKind
from apps.core.models import Policy, ReasonCode, User
from apps.core.services import require_permission, resolve_reason
from apps.orders.models import (
    AuthorizationKind,
    BillingStatus,
    FulfilmentStatus,
    OrderSource,
    PerformAuthorization,
    PrescriptionDetail,
    ServiceLine,
)
from apps.patients.models import Patient
from apps.visits.models import Visit, VisitStatus
from domain import service_line as dsl
from domain.audit import Approval
from domain.errors import DomainError

__all__ = [
    "ORDERABLE_KINDS",
    "AgedLine",
    "DoctorLine",
    "LineInput",
    "apply_credit",
    "apply_invoiced",
    "authorize_perform_first",
    "authorize_stay",
    "cancel_line",
    "cancel_line_remainder",
    "create_replacement",
    "create_service_lines",
    "doctor_line",
    "doctor_lines",
    "doctor_status",
    "given_units",
    "line_state",
    "line_status",
    "lock_lines",
    "lock_patient",
    "open_units",
    "order_performed",
    "orderable_services",
    "perform_line",
    "report_paid_not_performed",
    "report_performed_by_authorization",
    "report_requested_not_invoiced",
    "revoke_authorization",
    "set_line_payer",
    "start_line",
    "sync_settlement",
    "whole_quantity",
    "withdraw_order",
    "withdraw_reasons",
    "worklist",
    "worklist_lines",
]

#: Kinds whose performing department falls back to the visit's department.
_VISIT_DEPARTMENT_KINDS = {ServiceKind.CONSULTATION, ServiceKind.BED}
_PRESCRIPTION_FIELDS = {
    "dose",
    "dose_quantity",
    "route",
    "frequency_code",
    "frequency_per_day",
    "duration_days",
    "as_needed",
    "instructions",
}


def _billing() -> ModuleType:
    """``apps.billing.services`` (credit notes); imported lazily to avoid an import cycle."""
    return importlib.import_module("apps.billing.services")


def _pharmacy() -> ModuleType:
    """``apps.pharmacy.services`` (dispensed units); imported lazily."""
    return importlib.import_module("apps.pharmacy.services")


# --- shared helpers --------------------------------------------------------------------------


def lock_patient(patient_id: int) -> Patient:
    """Lock the patient row: the first lock of every money operation on that patient.

    Lock order across the financial engine: shift, patient, payment, invoice, credit note,
    service lines. Taking the patient first serializes all money work of one patient, so
    concurrent allocations, rejections, credit notes and approvals cannot interleave.

    A merged file also locks its surviving file (always after it: a file is locked before
    the file it was merged into), so money work on any file of one person serializes on the
    survivor (FEATURES 1.4).

    ``FOR NO KEY UPDATE``: money work serializes on the row, but the deferred foreign-key
    checks of other transactions' rows that reference the patient (``FOR KEY SHARE`` at
    commit) never wait on it, so they cannot close a deadlock cycle.
    """
    patient = Patient.objects.select_for_update(no_key=True).get(pk=patient_id)
    seen = {patient.pk}
    current = patient
    while current.merged_into_id is not None and current.merged_into_id not in seen:
        current = Patient.objects.select_for_update(no_key=True).get(pk=current.merged_into_id)
        seen.add(current.pk)
    return patient


def whole_quantity(value: Decimal | int | None, name: str = "quantity") -> int:
    """A whole number of units >= 1 (``INVALID_QUANTITY`` otherwise)."""
    if value is None or isinstance(value, bool):
        raise DomainError("INVALID_QUANTITY", f"{name} must be a whole number >= 1")
    dec = Decimal(value)
    if not dec.is_finite() or dec != dec.to_integral_value() or dec < 1:
        raise DomainError(
            "INVALID_QUANTITY", f"{name} must be a whole number >= 1", **{name: str(value)}
        )
    return int(dec)


def line_status(line: ServiceLine) -> dsl.LineStatus:
    """The domain snapshot of a stored line.

    A revoked authorization still covers work performed before the revocation (it never
    undoes work); revocation is refused while unpaid work is in progress.
    """
    auth = line.authorization
    authorized = auth is not None and (
        auth.revoked_at is None or line.fulfilment_status == FulfilmentStatus.PERFORMED
    )
    return dsl.LineStatus(
        dsl.BillingStatus(line.billing_status),
        dsl.FulfilmentStatus(line.fulfilment_status),
        authorized,
    )


def line_state(line: ServiceLine) -> dsl.LineState:
    """Display state: requested, invoiced, paid, performed or cancelled (FEATURES 4.1)."""
    return dsl.derived_state(
        dsl.BillingStatus(line.billing_status), dsl.FulfilmentStatus(line.fulfilment_status)
    )


def doctor_status(line: ServiceLine) -> dsl.DoctorStatus:
    """What the ordering doctor sees: requested, paid, in progress, done or cancelled
    (FEATURES 3.7; no prices)."""
    status = line_status(line)
    return dsl.doctor_status(status.billing, status.fulfilment, authorized=status.authorized)


def given_units(line: ServiceLine) -> int:
    """Units already handed out for the line (dispensed drug or consumable units)."""
    return int(_pharmacy().dispensed_quantity(line))


def open_units(line: ServiceLine) -> int:
    """Units of the line that may still be performed or dispensed (invariant 1).

    The ordered quantity less units an approved credit note took back and units already
    given (``domain.service_line.open_quantity``).
    """
    return dsl.open_quantity(
        whole_quantity(line.quantity),
        credited=_billing().credited_quantity(line),
        given=given_units(line),
    )


def _share_authorizations(lines: Sequence[ServiceLine]) -> None:
    """Lock the lines' authorizations ``FOR SHARE`` (after the line locks) and reload them.

    A revocation locks the same rows ``FOR UPDATE`` after the lines, so a line's work and a
    revocation of its authorization serialize, and the eligibility read here is current.
    """
    ids = sorted({ln.authorization_id for ln in lines if ln.authorization_id is not None})
    if not ids:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM orders_performauthorization WHERE id = ANY(%s) ORDER BY id FOR SHARE",
            [ids],
        )
    fresh = PerformAuthorization.objects.in_bulk(ids)
    for ln in lines:
        if ln.authorization_id is not None:
            ln.authorization = fresh[ln.authorization_id]


def _lock_lines(ids: Iterable[int]) -> list[ServiceLine]:
    rows = list(
        ServiceLine.objects.select_for_update(of=("self",))
        .select_related("authorization")
        .filter(pk__in=list(ids))
        .order_by("id")
    )
    _share_authorizations(rows)
    return rows


def lock_lines(ids: Iterable[int]) -> list[ServiceLine]:
    """Lock service lines ``FOR UPDATE`` (id order), then their authorizations ``FOR SHARE``,
    reloaded: the lock order of every work path (dispense, samples, results)."""
    return _lock_lines(ids)


def _lock_line(line: ServiceLine | int) -> ServiceLine:
    pk = line if isinstance(line, int) else line.pk
    found = _lock_lines([pk])
    if not found:
        raise ServiceLine.DoesNotExist(f"service line {pk}")
    return found[0]


def _patient_id_of(line: ServiceLine | int) -> int:
    pk = line if isinstance(line, int) else line.pk
    return int(ServiceLine.objects.filter(pk=pk).values_list("visit__patient_id", flat=True).get())


def _store(line: ServiceLine, status: dsl.LineStatus, **fields: Any) -> ServiceLine:
    """Save a transition: the two statuses plus the documenting fields."""
    line.billing_status = str(status.billing)
    line.fulfilment_status = str(status.fulfilment)
    for name, value in fields.items():
        setattr(line, name, value)
    line.save(update_fields=["billing_status", "fulfilment_status", *fields.keys(), "updated_at"])
    return line


def _approval(actor: User, at: datetime, reason: ReasonCode, note: str) -> Approval:
    return Approval(actor.pk, at, note.strip(), reason.code)


# --- ordering --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LineInput:
    """One ordered service. ``prescription`` holds ``PrescriptionDetail`` fields (drugs)."""

    service: Service | int
    quantity: Decimal | int = 1
    order_source: str = OrderSource.DOCTOR
    note: str = ""
    pre_approval_ref: str = ""
    prescription: Mapping[str, Any] | None = None


def _as_input(item: LineInput | Mapping[str, Any]) -> LineInput:
    if isinstance(item, LineInput):
        return item
    unknown = set(item) - set(LineInput.__slots__)
    if unknown:
        raise DomainError("INVALID_ORDER_LINE", "Unknown order fields", fields=sorted(unknown))
    return LineInput(**item)


def create_service_lines(
    visit: Visit, items: Sequence[LineInput | Mapping[str, Any]], actor: User
) -> list[ServiceLine]:
    """Add requested lines to an open visit (FLOW steps 1 and 3, FEATURES 3.5).

    Each line copies the service kind and performing department, and the visit's payer. The
    quantity is a whole number of units (base units for drugs).

    Raises:
        DomainError: ``VISIT_NOT_OPEN``, ``ORDER_EMPTY``, ``SERVICE_INACTIVE``,
            ``INVALID_QUANTITY``, ``INVALID_ORDER_SOURCE``, ``INVALID_ORDER_LINE``,
            ``PRESCRIPTION_NOT_DRUG``.
    """
    inputs = [_as_input(item) for item in items]
    if not inputs:
        raise DomainError("ORDER_EMPTY", "Nothing to order")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="order services"):
        locked = Visit.objects.select_for_update().get(pk=visit.pk)
        if locked.status != VisitStatus.OPEN:
            raise DomainError("VISIT_NOT_OPEN", "Orders can be added only to an open visit")
        ids = {i.service if isinstance(i.service, int) else i.service.pk for i in inputs}
        services = Service.objects.in_bulk(list(ids))
        created: list[ServiceLine] = []
        for item in inputs:
            sid = item.service if isinstance(item.service, int) else item.service.pk
            service = services.get(sid)
            if service is None or not service.active:
                raise DomainError(
                    "SERVICE_INACTIVE", "The service is unknown or inactive", service_id=sid
                )
            quantity = whole_quantity(item.quantity)
            if item.order_source not in OrderSource.values:
                raise DomainError(
                    "INVALID_ORDER_SOURCE", "Unknown order source", order_source=item.order_source
                )
            if item.prescription is not None:
                if service.kind != ServiceKind.DRUG:
                    raise DomainError(
                        "PRESCRIPTION_NOT_DRUG", "Only drug lines carry a prescription"
                    )
                unknown = set(item.prescription) - _PRESCRIPTION_FIELDS
                if unknown:
                    raise DomainError(
                        "INVALID_ORDER_LINE", "Unknown prescription fields", fields=sorted(unknown)
                    )
            department_id = service.department_id
            if department_id is None and service.kind in _VISIT_DEPARTMENT_KINDS:
                department_id = locked.department_id
            line = ServiceLine.objects.create(
                visit=locked,
                service=service,
                kind=service.kind,
                department_id=department_id,
                quantity=Decimal(quantity),
                payer_id=locked.payer_id,
                pre_approval_ref=item.pre_approval_ref.strip()[:100],
                order_source=item.order_source,
                order_note=item.note.strip()[:500],
                ordered_by=actor,
            )
            if item.prescription is not None:
                PrescriptionDetail.objects.create(line=line, **dict(item.prescription))
            created.append(line)
    return created


# --- work ------------------------------------------------------------------------------------


def worklist(
    kinds: str | Iterable[str],
    *,
    department: int | None = None,
    visit: Visit | None = None,
) -> QuerySet[ServiceLine]:
    """Lines a department may work on now (FEATURES 4.3, invariant 1).

    Open fulfilment (pending or in progress) AND (settled OR an unrevoked perform-first
    authorization), oldest order first. Matches ``domain.service_line.can_enter_worklist``.
    """
    wanted = [kinds] if isinstance(kinds, str) else list(kinds)
    qs = ServiceLine.objects.filter(
        Q(billing_status=BillingStatus.SETTLED)
        | Q(authorization__isnull=False, authorization__revoked_at__isnull=True),
        kind__in=wanted,
        fulfilment_status__in=[FulfilmentStatus.PENDING, FulfilmentStatus.IN_PROGRESS],
    )
    if department is not None:
        qs = qs.filter(department_id=department)
    if visit is not None:
        qs = qs.filter(visit=visit)
    return qs.select_related("visit", "service", "authorization").order_by("ordered_at", "id")


def start_line(line: ServiceLine, actor: User, *, at: datetime | None = None) -> ServiceLine:
    """``pending`` -> ``in_progress`` (e.g. sample received). Needs eligibility.

    Raises:
        DomainError: ``LINE_NOT_ELIGIBLE``, ``LINE_ALREADY_STARTED``,
            ``LINE_ALREADY_PERFORMED``, ``LINE_CANCELLED``.
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="start line"):
        locked = _lock_line(line)
        new = dsl.start(line_status(locked))
        return _store(locked, new, started_at=at or timezone.now(), started_by=actor)


def perform_line(
    line: ServiceLine,
    actor: User,
    *,
    performed_quantity: Decimal | int | None = None,
    note: str = "",
    at: datetime | None = None,
) -> ServiceLine:
    """Mark the line performed (result approved, drug dispensed, procedure done).

    ``performed_quantity`` records a partial performance (partial dispense); the remainder is
    then closed with :func:`cancel_line_remainder` or left to a later invoice. Units an
    approved credit note took back are never performed: the performed quantity is at most
    the ordered less the credited units, and defaults to that when units were credited.

    Raises:
        DomainError: ``LINE_NOT_ELIGIBLE`` (neither settled nor authorized, invariant 1),
            ``LINE_ALREADY_PERFORMED``, ``LINE_CANCELLED``, ``INVALID_QUANTITY``.
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="perform line"):
        locked = _lock_line(line)
        return _perform(locked, actor, performed_quantity=performed_quantity, note=note, at=at)


def _perform(
    locked: ServiceLine,
    actor: User,
    *,
    performed_quantity: Decimal | int | None = None,
    note: str = "",
    at: datetime | None = None,
) -> ServiceLine:
    new = dsl.perform(line_status(locked))
    credited = _billing().credited_quantity(locked)
    performable = dsl.open_quantity(whole_quantity(locked.quantity), credited=credited)
    fields: dict[str, Any] = {
        "performed_at": at or timezone.now(),
        "performed_by": actor,
        "performed_note": note.strip()[:500],
    }
    if performed_quantity is not None:
        qty = Decimal(performed_quantity)
        if not qty.is_finite() or qty <= 0 or qty > performable:
            raise DomainError(
                "INVALID_QUANTITY",
                "Performed quantity must be above zero and at most the units still billed",
                performed_quantity=str(performed_quantity),
                quantity=str(locked.quantity),
                credited=credited,
            )
        fields["performed_quantity"] = qty
    elif credited > 0:
        fields["performed_quantity"] = Decimal(performable)
    return _store(locked, new, **fields)


# --- perform-first ---------------------------------------------------------------------------


def authorize_perform_first(
    lines: Sequence[ServiceLine],
    *,
    actor: User,
    reason: ReasonCode | str,
    kind: str = AuthorizationKind.OTHER,
    note: str = "",
    approval_reference: str = "",
    requested_by: User | None = None,
) -> PerformAuthorization:
    """Allow open, unpaid lines of one visit to be performed before payment (FEATURES 4.4).

    The authorizer needs ``orders.authorize_perform_first`` and one of the roles in
    ``Policy.perform_first_roles`` (or the admin role / a superuser). An insurance approval
    carries the payer's approval reference.

    Raises:
        PermissionRequired: the actor lacks ``orders.authorize_perform_first``.
        DomainError: ``PERFORM_FIRST_NOT_ALLOWED``, ``REASON_REQUIRED``, ``REASON_UNKNOWN``,
            ``REASON_NOTE_REQUIRED``, ``INVALID_AUTHORIZATION_KIND``,
            ``APPROVAL_REFERENCE_REQUIRED``, ``ORDER_EMPTY``, ``LINES_NOT_ONE_VISIT``,
            ``VISIT_NOT_OPEN``, ``LINE_ALREADY_AUTHORIZED``, ``LINE_ALREADY_SETTLED``,
            ``LINE_ALREADY_PERFORMED``, ``LINE_CANCELLED``.
    """
    require_permission(actor, "orders.authorize_perform_first")
    roles = set(actor.role_codes())
    allowed = set(Policy.load().perform_first_roles or [])
    if not (actor.is_superuser or "admin" in roles or roles & allowed):
        raise DomainError(
            "PERFORM_FIRST_NOT_ALLOWED",
            "Your role may not authorize perform-first exceptions",
            allowed_roles=sorted(allowed),
        )
    reason_obj = resolve_reason(reason, "perform_first", note)
    if kind not in AuthorizationKind.values:
        raise DomainError("INVALID_AUTHORIZATION_KIND", "Unknown authorization kind", kind=kind)
    ref = approval_reference.strip()
    if kind == AuthorizationKind.INSURANCE_APPROVAL and not ref:
        raise DomainError(
            "APPROVAL_REFERENCE_REQUIRED", "An insurance approval needs the payer's reference"
        )
    if not lines:
        raise DomainError("ORDER_EMPTY", "Choose the lines to authorize")
    with (
        transaction.atomic(),
        pghistory.context(user=actor.pk, reason=f"perform first: {reason_obj.code}"),
    ):
        lock_patient(_patient_id_of(lines[0]))
        locked = _lock_lines(ln.pk for ln in lines)
        visits = {ln.visit_id for ln in locked}
        if len(visits) != 1 or len(locked) != len({ln.pk for ln in lines}):
            raise DomainError("LINES_NOT_ONE_VISIT", "Authorize lines of one visit at a time")
        visit = Visit.objects.get(pk=visits.pop())
        if visit.status != VisitStatus.OPEN:
            raise DomainError("VISIT_NOT_OPEN", "The visit is not open")
        now = timezone.now()
        approval = _approval(actor, now, reason_obj, note)
        for ln in locked:
            dsl.authorize(line_status(ln), approval)
        auth = PerformAuthorization.objects.create(
            visit=visit,
            kind=kind,
            reason_code=reason_obj,
            reason_note=note.strip(),
            approval_reference=ref[:100],
            requested_by=requested_by,
            authorized_by=actor,
            authorized_at=now,
        )
        for ln in locked:
            ln.authorization = auth
            ln.save(update_fields=["authorization", "updated_at"])
    return auth


def revoke_authorization(auth: PerformAuthorization, *, actor: User, note: str) -> None:
    """Withdraw a perform-first authorization for lines that have not started.

    Work already performed stays performed. Revoking while an unpaid line has work under way
    (in progress: a sample taken, part of a prescription dispensed) is refused: finish or
    cancel that line first.

    The authorization's lines are locked first, then the authorization (the order every
    work path uses: line, then authorization), so a line starting concurrently is either
    seen as started here or sees the revocation.

    Raises:
        PermissionRequired: the actor lacks ``orders.authorize_perform_first``.
        DomainError: ``REASON_REQUIRED``, ``AUTHORIZATION_REVOKED``, ``AUTHORIZATION_IN_USE``.
    """
    require_permission(actor, "orders.authorize_perform_first")
    text = note.strip()
    if not text:
        raise DomainError("REASON_REQUIRED", "Say why the authorization is withdrawn")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"revoke: {text}"):
        lines = list(
            ServiceLine.objects.select_for_update().filter(authorization_id=auth.pk).order_by("id")
        )
        locked = PerformAuthorization.objects.select_for_update().get(pk=auth.pk)
        if locked.revoked_at is not None:
            raise DomainError("AUTHORIZATION_REVOKED", "The authorization is already revoked")
        busy = [
            ln.pk
            for ln in lines
            if ln.billing_status != BillingStatus.SETTLED
            and (
                ln.fulfilment_status == FulfilmentStatus.IN_PROGRESS
                or (ln.fulfilment_status == FulfilmentStatus.PENDING and given_units(ln) > 0)
            )
        ]
        if busy:
            raise DomainError(
                "AUTHORIZATION_IN_USE",
                "Unpaid work under this authorization is in progress",
                line_ids=busy,
            )
        locked.revoked_at = timezone.now()
        locked.revoked_by = actor
        locked.revoke_note = text
        locked.save(update_fields=["revoked_at", "revoked_by", "revoke_note"])


def authorize_stay(visit: Visit, *, actor: User, note: str) -> PerformAuthorization:
    """The documented perform-first exception of an inpatient stay (FEATURES 10.5).

    Bed nights are given before they are billed (charged in arrears), so the admission
    records who allowed it and why (invariant 4); the nights are then ordered performed
    under it (:func:`order_performed`). Called by ``apps.visits.services.admit``.
    """
    reason = resolve_reason("OTHER", "perform_first", note=note)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="inpatient stay"):
        return PerformAuthorization.objects.create(
            visit=visit,
            kind=AuthorizationKind.CREDIT_ACCOUNT,
            reason_code=reason,
            reason_note=note.strip()[:1000],
            authorized_by=actor,
            authorized_at=timezone.now(),
        )


def order_performed(
    visit: Visit,
    items: Sequence[LineInput | Mapping[str, Any]],
    actor: User,
    *,
    authorization: PerformAuthorization,
    at: datetime | None = None,
) -> list[ServiceLine]:
    """Order lines that were already given under ``authorization`` (bed nights in arrears).

    Each line is created requested, put under the authorization and performed at ``at``,
    so it never shows as paid-not-performed or as work waiting in a work list.

    Raises:
        DomainError: the errors of :func:`create_service_lines`, ``AUTHORIZATION_REVOKED``,
            ``LINES_NOT_ONE_VISIT`` (the authorization is of another visit).
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="order performed"):
        auth = PerformAuthorization.objects.select_for_update().get(pk=authorization.pk)
        if auth.visit_id != visit.pk:
            raise DomainError("LINES_NOT_ONE_VISIT", "The authorization is of another visit")
        if auth.revoked_at is not None:
            raise DomainError("AUTHORIZATION_REVOKED", "The authorization is revoked")
        lines = create_service_lines(visit, items, actor)
        when = at or timezone.now()
        out = []
        for ln in _lock_lines(x.pk for x in lines):
            ln.authorization = auth
            ln.save(update_fields=["authorization", "updated_at"])
            out.append(_perform(ln, actor, at=when))
    return out


def set_line_payer(
    line: ServiceLine,
    *,
    payer: Any | None,
    actor: User,
    note: str,
    pre_approval_ref: str | None = None,
) -> ServiceLine:
    """Bill an unbilled line to another payer of the patient, or to cash (FEATURES 5.6).

    The payer must be one the patient holds a valid coverage of on the visit date (any file
    of the person). The line leaves draft invoices so it is priced again for its payer.

    Raises:
        DomainError: ``REASON_REQUIRED``, ``LINE_NOT_BILLABLE`` (already invoiced),
            ``LINE_CANCELLED``, ``COVERAGE_INVALID``.
    """
    text = note.strip()
    if not text:
        raise DomainError("REASON_REQUIRED", "Say why the line's payer changes")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"line payer: {text}"):
        lock_patient(_patient_id_of(line))
        locked = _lock_line(line)
        if locked.billing_status != BillingStatus.UNBILLED:
            raise DomainError("LINE_NOT_BILLABLE", "Only an unbilled line can change payer")
        if locked.fulfilment_status == FulfilmentStatus.CANCELLED:
            raise DomainError("LINE_CANCELLED", "The line is cancelled")
        if payer is not None:
            visit = Visit.objects.select_related("patient").get(pk=locked.visit_id)
            on = timezone.localdate(visit.created_at)
            patients = importlib.import_module("apps.patients.services")
            valid = {c.payer_id for c in patients.coverages_valid_on(visit.patient, on)}
            if payer.pk not in valid or not payer.active:
                raise DomainError(
                    "COVERAGE_INVALID", "The patient has no valid coverage of this payer"
                )
        _billing().drop_from_drafts(locked, actor=actor)
        locked.payer = payer
        fields = ["payer", "updated_at"]
        if pre_approval_ref is not None:
            locked.pre_approval_ref = pre_approval_ref.strip()[:100]
            fields.append("pre_approval_ref")
        locked.save(update_fields=fields)
    return locked


# --- cancelling ------------------------------------------------------------------------------


def _credit_approver(actor: User, approver: User | None) -> User:
    """Who approves the credit note of a billed line: a ``billing.approve_credit_note`` holder.

    A doctor, pharmacist or lab supervisor may cancel lines, but money moves back only with
    a cashier supervisor's or accountant's approval (FEATURES 5.11, ARCHITECTURE 4.10).
    """
    chosen = approver or actor
    require_permission(chosen, "billing.approve_credit_note")
    return chosen


def cancel_line(
    line: ServiceLine,
    reason: ReasonCode | str,
    actor: User,
    *,
    note: str = "",
    open_refund: bool = True,
    approver: User | None = None,
    require_unbilled: bool = False,
) -> ServiceLine:
    """Cancel an open line with a reason (FEATURES 4.2, invariant 4).

    With ``require_unbilled`` (the ordering side's withdrawal) a line found billed under the
    row lock is refused with ``CREDIT_NOTE_REQUIRED`` instead of being credited, so an
    invoice approved concurrently never routes through the credit-note path here.

    * Unbilled: the line is cancelled and removed from any draft invoice (FLOW step 4: the
      patient refuses a test and it does not enter the invoice).
    * Invoiced or settled: a credit note for the rest of the line is issued by the actor and
      approved by ``approver`` (default the actor; a ``billing.approve_credit_note`` holder);
      the line becomes credited and cancelled. Patient money on it is de-allocated into
      patient credit and, with ``open_refund``, a refund request is opened for it
      (FLOW 5: the refund procedure opens automatically).
    * Partly dispensed: the dispensed units are performed and only the rest is cancelled
      (:func:`cancel_line_remainder`); the given units stay billed (invariants 1 and 5).

    Raises:
        PermissionRequired: a billed line's approver lacks ``billing.approve_credit_note``.
        DomainError: ``REASON_REQUIRED``, ``REASON_UNKNOWN``, ``REASON_NOTE_REQUIRED``,
            ``LINE_ALREADY_CANCELLED``, ``LINE_ALREADY_PERFORMED`` (credit a performed line
            instead), ``LINE_NOT_ELIGIBLE`` (dispensed units of an unpaid line: collect the
            payment first), ``CLAIM_LINE_LOCKED``.
    """
    reason_obj = resolve_reason(reason, "line_cancel", note)
    with (
        transaction.atomic(),
        pghistory.context(user=actor.pk, reason=f"cancel line: {reason_obj.code}"),
    ):
        lock_patient(_patient_id_of(line))
        locked = _lock_line(line)
        now = timezone.now()
        approval = _approval(actor, now, reason_obj, note)
        status = line_status(locked)
        if require_unbilled and status.billing != dsl.BillingStatus.UNBILLED:
            raise DomainError(
                "CREDIT_NOTE_REQUIRED", "A billed order is withdrawn by a credit note at billing"
            )
        given = given_units(locked) if status.fulfilment in dsl.ACTIVE_FULFILMENT else 0
        if given > 0:
            _perform(locked, actor, performed_quantity=given, note=note, at=now)
            return _cancel_remainder(
                locked, reason_obj, actor, note=note, open_refund=open_refund, approver=approver
            )
        if status.billing in dsl.BILLED:
            dsl.cancel(status, approval, with_credit_note=True)
            _billing().credit_service_line(
                locked,
                actor=actor,
                line_reason=reason_obj,
                note=note,
                open_refund=open_refund,
                approver=_credit_approver(actor, approver),
            )
            locked.refresh_from_db()
            return locked
        new = dsl.cancel(status, approval)
        _billing().drop_from_drafts(locked, actor=actor)
        return _store(
            locked,
            new,
            cancelled_at=now,
            cancelled_by=actor,
            cancel_reason=reason_obj,
            cancel_note=note.strip(),
        )


def cancel_line_remainder(
    line: ServiceLine,
    reason: ReasonCode | str,
    actor: User,
    *,
    note: str = "",
    open_refund: bool = True,
    approver: User | None = None,
) -> ServiceLine:
    """Close the part of a partly performed line that will not be given (FEATURES 8.3).

    The line must be performed with ``performed_quantity`` below its units still billed. A
    billed line gets a credit note for the remaining units, never for units an earlier
    credit note already took back (``domain.service_line.remainder_to_credit``); its patient
    money becomes credit, with a refund request. An unbilled line will be invoiced for the
    performed quantity only. The cancellation reason, actor and time are recorded on the
    line (invariant 4).

    Raises:
        PermissionRequired: a billed line's approver lacks ``billing.approve_credit_note``.
        DomainError: ``LINE_NOT_PERFORMED``, ``LINE_NOTHING_REMAINING``, reason errors,
            ``CLAIM_LINE_LOCKED``.
    """
    reason_obj = resolve_reason(reason, "line_cancel", note)
    with (
        transaction.atomic(),
        pghistory.context(user=actor.pk, reason=f"cancel remainder: {reason_obj.code}"),
    ):
        lock_patient(_patient_id_of(line))
        locked = _lock_line(line)
        return _cancel_remainder(
            locked, reason_obj, actor, note=note, open_refund=open_refund, approver=approver
        )


def _cancel_remainder(
    locked: ServiceLine,
    reason_obj: ReasonCode,
    actor: User,
    *,
    note: str,
    open_refund: bool,
    approver: User | None,
) -> ServiceLine:
    if locked.fulfilment_status != FulfilmentStatus.PERFORMED:
        raise DomainError("LINE_NOT_PERFORMED", "Only a performed line has a remainder")
    done = locked.performed_quantity
    if done is None or locked.cancelled_at is not None:
        raise DomainError("LINE_NOTHING_REMAINING", "Nothing of the line is left to cancel")
    remainder = dsl.remainder_to_credit(
        whole_quantity(locked.quantity),
        credited=_billing().credited_quantity(locked),
        performed=whole_quantity(done, "performed_quantity"),
    )
    if locked.billing_status in (BillingStatus.INVOICED, BillingStatus.SETTLED):
        _billing().credit_service_line(
            locked,
            actor=actor,
            line_reason=reason_obj,
            note=note,
            quantity=remainder,
            open_refund=open_refund,
            approver=_credit_approver(actor, approver),
        )
        locked.refresh_from_db()
    locked.cancelled_at = timezone.now()
    locked.cancelled_by = actor
    locked.cancel_reason = reason_obj
    locked.cancel_note = note.strip()
    locked.save(
        update_fields=[
            "cancelled_at",
            "cancelled_by",
            "cancel_reason",
            "cancel_note",
            "updated_at",
        ]
    )
    return locked


# --- billing entry points (called by apps.billing.services under the patient lock) -----------


def apply_invoiced(line: ServiceLine, *, patient_due: Decimal, at: datetime) -> ServiceLine:
    """The line was frozen on an approved invoice; zero patient due settles it at once."""
    new = dsl.invoice(line_status(line), patient_due=patient_due)
    fields: dict[str, Any] = {"invoiced_at": at}
    if new.billing is dsl.BillingStatus.SETTLED:
        fields["settled_at"] = at
    return _store(line, new, **fields)


def sync_settlement(line: ServiceLine, *, outstanding: Decimal, at: datetime) -> bool:
    """Follow the line's patient outstanding: settled at zero, invoiced otherwise.

    Returns whether the stored billing status changed. Unbilled and credited lines are left
    alone.
    """
    old = line_status(line)
    new = dsl.apply_settlement(old, outstanding=outstanding)
    if new == old:
        return False
    settled = new.billing is dsl.BillingStatus.SETTLED
    _store(line, new, settled_at=at if settled else None)
    return True


def apply_credit(
    line: ServiceLine,
    *,
    approval: Approval,
    fully_credited: bool,
    actor: User,
    cancel_reason: ReasonCode,
    cancel_note: str,
) -> ServiceLine:
    """An approved credit note credited this line (all of it, or some units).

    A full credit makes the line ``credited``; an open line is also cancelled, with the
    cancellation documented (invariant 4). A partial credit changes no status, except that
    an open line whose every remaining unit is now given (part dispensed, the rest credited)
    is performed with the given units, so it does not wait in a work list forever.
    """
    old = line_status(line)
    new = dsl.credit(old, approval, fully_credited=fully_credited)
    if new == old:
        given = given_units(line) if old.fulfilment in dsl.ACTIVE_FULFILMENT else 0
        if given > 0 and open_units(line) == 0 and dsl.can_enter_worklist(old):
            return _perform(line, actor, performed_quantity=given, at=approval.at)
        return line
    fields: dict[str, Any] = {"credited_at": approval.at}
    if new.fulfilment != old.fulfilment:
        fields.update(
            cancelled_at=approval.at,
            cancelled_by=actor,
            cancel_reason=cancel_reason,
            cancel_note=cancel_note.strip(),
        )
    return _store(line, new, **fields)


def create_replacement(line: ServiceLine, *, approval: Approval, actor: User) -> ServiceLine:
    """A new line that re-bills a credited one (a correction after a credit note).

    A performed original yields an unbilled line already performed under a documented
    perform-first authorization (the service was given; only billing is corrected). A
    cancelled original yields a fresh requested line.
    """
    new = dsl.replacement(line_status(line), approval)
    auth = None
    performed: dict[str, Any] = {}
    if new.fulfilment is dsl.FulfilmentStatus.PERFORMED:
        reason = resolve_reason("OTHER", "perform_first", note=approval.reason_text or "rebill")
        auth = PerformAuthorization.objects.create(
            visit_id=line.visit_id,
            kind=AuthorizationKind.OTHER,
            reason_code=reason,
            reason_note=f"correction of line {line.pk}: {approval.reason_text}"[:1000],
            authorized_by=actor,
            authorized_at=approval.at,
        )
        performed = {
            "performed_at": line.performed_at,
            "performed_by_id": line.performed_by_id,
            "performed_quantity": line.performed_quantity,
            "performed_note": line.performed_note,
        }
    return ServiceLine.objects.create(
        visit_id=line.visit_id,
        service_id=line.service_id,
        kind=line.kind,
        department_id=line.department_id,
        quantity=line.quantity,
        payer_id=line.payer_id,
        pre_approval_ref=line.pre_approval_ref,
        order_source=line.order_source,
        order_note=f"replaces line {line.pk}"[:500],
        ordered_by=actor,
        billing_status=str(new.billing),
        fulfilment_status=str(new.fulfilment),
        authorization=auth,
        **performed,
    )


# --- the doctor's view (FEATURES 3.5, 3.7, 4.1, 4.2; no prices) ------------------------------

#: Kinds a doctor orders from the catalog (the consultation fee and bed days are automatic).
ORDERABLE_KINDS: tuple[str, ...] = (
    ServiceKind.LAB,
    ServiceKind.PROCEDURE,
    ServiceKind.DRUG,
    ServiceKind.CONSUMABLE,
)


def orderable_services(
    query: str = "", *, kinds: Sequence[str] | None = None, limit: int = 30
) -> list[Service]:
    """Active catalog services a doctor may order, by code prefix or words of the name.

    Words match the Arabic or English name, or a drug's generic or brand name, folded like
    patient search (hamza, ta marbuta, case). Drugs carry their stock item (form, strength,
    base unit, classes) for the prescription builder. Never prices (FEATURES 3.8).

    Raises:
        DomainError: ``INVALID_KIND`` for a kind outside :data:`ORDERABLE_KINDS`.
    """
    from apps.core.db import NormalizeText
    from apps.patients import services as patient_services

    wanted = list(kinds) if kinds else list(ORDERABLE_KINDS)
    unknown = sorted(set(wanted) - set(ORDERABLE_KINDS))
    if unknown:
        raise DomainError("INVALID_KIND", "These kinds cannot be ordered", kinds=unknown)
    qs: QuerySet[Service] = Service.objects.filter(active=True, kind__in=wanted)
    term = " ".join(query.split())
    if term:
        words = [w for w in patient_services.normalize_text(term).split(" ") if w]
        name_match = Q()
        for word in words:
            name_match &= (
                Q(ar__contains=word)
                | Q(en__contains=word)
                | Q(drug_generic__contains=word)
                | Q(drug_brand__contains=word)
            )
        qs = qs.annotate(
            ar=NormalizeText("name_ar"),
            en=NormalizeText("name_en"),
            drug_generic=NormalizeText("stock_item__generic_name"),
            drug_brand=NormalizeText("stock_item__brand_name"),
        ).filter(Q(code__istartswith=term.replace(" ", "")) | name_match)
    return list(
        qs.select_related("department", "stock_item")
        .prefetch_related("stock_item__drug_classes")
        .order_by("kind", "sort_order", "code")[: max(1, min(limit, 100))]
    )


@dataclass(frozen=True, slots=True)
class DoctorLine:
    """One order of a visit as its doctor sees it: progress, never prices (FEATURES 3.7)."""

    line: ServiceLine
    status: dsl.DoctorStatus
    can_cancel: bool
    result: Any | None


def _cancellable_by_orderer(line: ServiceLine) -> bool:
    """Only a line that has not reached the cashier: unbilled, pending, nothing given."""
    return (
        line.billing_status == BillingStatus.UNBILLED
        and line.fulfilment_status == FulfilmentStatus.PENDING
        and not line.dispense_lines.all()
    )


def doctor_lines(visit: Visit) -> list[DoctorLine]:
    """The visit's clinical orders (lab, procedure, drug, consumable), oldest first, with the
    doctor's status and the approved lab result inline (FEATURES 3.7). No prices."""
    from apps.lab.models import ResultStatus, ResultVersion

    lines = list(
        ServiceLine.objects.filter(visit=visit, kind__in=ORDERABLE_KINDS)
        .select_related(
            "service",
            "authorization",
            "prescription",
            "ordered_by",
            "cancel_reason",
            "cancelled_by",
        )
        .prefetch_related("allergy_overrides__overridden_by", "dispense_lines")
        .order_by("id")
    )
    results = {
        v.result_set.service_line_id: v
        for v in ResultVersion.objects.filter(
            result_set__service_line__in=lines, status=ResultStatus.APPROVED
        )
        .select_related("result_set__test__service", "result_set__service_line")
        .prefetch_related("values__parameter")
    }
    return [
        DoctorLine(
            line=ln,
            status=doctor_status(ln),
            can_cancel=_cancellable_by_orderer(ln),
            result=results.get(ln.pk),
        )
        for ln in lines
    ]


def doctor_line(line: ServiceLine) -> DoctorLine:
    """One line in the doctor's view (after an order or a cancellation).

    Raises:
        DomainError: ``LINE_NOT_CLINICAL`` (a consultation fee or bed day).
    """
    found = [d for d in doctor_lines(line.visit) if d.line.pk == line.pk]
    if not found:
        raise DomainError("LINE_NOT_CLINICAL", "This line is not a clinical order")
    return found[0]


def withdraw_order(line: ServiceLine, *, reason: str, note: str, actor: User) -> DoctorLine:
    """Withdraw an order that has not reached the cashier, with a reason (FEATURES 4.2).

    A billed order is credited by billing instead; the ordering side never moves money. The
    early check gives a fast answer; ``cancel_line`` repeats it under the row lock.

    Raises:
        DomainError: ``CREDIT_NOTE_REQUIRED``, ``LINE_NOT_CLINICAL``,
            ``LINE_ALREADY_CANCELLED``, ``LINE_ALREADY_PERFORMED``, the reason errors.
    """
    if line.kind not in ORDERABLE_KINDS:
        raise DomainError("LINE_NOT_CLINICAL", "This line is not a clinical order")
    if line.billing_status != BillingStatus.UNBILLED:
        raise DomainError(
            "CREDIT_NOTE_REQUIRED", "A billed order is withdrawn by a credit note at billing"
        )
    cancel_line(line, reason, actor, note=note, open_refund=False, require_unbilled=True)
    return doctor_line(line)


def withdraw_reasons() -> list[ReasonCode]:
    """The active line cancellation reasons a withdrawal chooses from (FEATURES 4.2)."""
    return list(
        ReasonCode.objects.filter(category="line_cancel", active=True).order_by(
            "sort_order", "code"
        )
    )


def worklist_lines(kinds: Sequence[str], *, department: int | None = None) -> list[ServiceLine]:
    """A department's work list (FEATURES 4.3): only lines it may work on now (invariant 1).

    Raises:
        DomainError: ``INVALID_KIND``.
    """
    unknown = sorted(set(kinds) - set(ServiceKind.values))
    if not kinds or unknown:
        raise DomainError("INVALID_KIND", "Unknown service kinds", kinds=unknown)
    return list(
        worklist(kinds, department=department).select_related(
            "visit__patient", "department", "prescription"
        )[:500]
    )


# --- exception reports (FEATURES 4.5, 12.2) --------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgedLine:
    """A line in an exception report with its age in whole days."""

    line: ServiceLine
    age_days: int


def _age_days(since: datetime | None, today: date) -> int:
    if since is None:
        return 0
    return max(0, (today - timezone.localdate(since)).days)


def _report_rows(qs: QuerySet[ServiceLine], since_field: str, limit: int) -> list[AgedLine]:
    today = timezone.localdate()
    rows = list(
        qs.select_related(
            "visit__patient",
            "service",
            "department",
            "ordered_by",
            "authorization__authorized_by",
            "authorization__reason_code",
        )[: max(1, min(limit, 1000))]
    )
    return [AgedLine(ln, _age_days(getattr(ln, since_field), today)) for ln in rows]


def report_requested_not_invoiced(*, min_age_days: int = 0, limit: int = 500) -> list[AgedLine]:
    """Ordered lines that never reached an approved invoice, oldest first (FEATURES 4.5).

    Open (pending), unbilled and not under a perform-first authorization (those are in
    :func:`report_performed_by_authorization`), at least ``min_age_days`` old.
    """
    qs = ServiceLine.objects.filter(
        billing_status=BillingStatus.UNBILLED,
        fulfilment_status=FulfilmentStatus.PENDING,
        authorization__isnull=True,
    )
    if min_age_days > 0:
        qs = qs.filter(ordered_at__lte=timezone.now() - timedelta(days=min_age_days))
    return _report_rows(qs.order_by("ordered_at", "id"), "ordered_at", limit)


def report_paid_not_performed(*, min_age_days: int = 0, limit: int = 500) -> list[AgedLine]:
    """Settled lines still waiting to be performed (the first leak of pay-first), oldest
    settlement first; the age counts from settlement (FEATURES 4.5)."""
    qs = ServiceLine.objects.filter(
        billing_status=BillingStatus.SETTLED,
        fulfilment_status__in=[FulfilmentStatus.PENDING, FulfilmentStatus.IN_PROGRESS],
    )
    if min_age_days > 0:
        qs = qs.filter(settled_at__lte=timezone.now() - timedelta(days=min_age_days))
    return _report_rows(qs.order_by("settled_at", "id"), "settled_at", limit)


def report_performed_by_authorization(
    *, date_from: date | None = None, date_to: date | None = None, limit: int = 500
) -> list[AgedLine]:
    """Lines performed under a perform-first authorization, newest first, with who allowed
    them and why; the age counts from performance (FEATURES 4.5)."""
    qs = ServiceLine.objects.filter(
        fulfilment_status=FulfilmentStatus.PERFORMED, authorization__isnull=False
    )
    if date_from is not None:
        qs = qs.filter(performed_at__date__gte=date_from)
    if date_to is not None:
        qs = qs.filter(performed_at__date__lte=date_to)
    return _report_rows(qs.order_by("-performed_at", "-id"), "performed_at", limit)
