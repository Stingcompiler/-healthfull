"""Read models of the patient portal (FEATURES 15.2). Each function takes the signed-in
:class:`~apps.portal.services.PortalPrincipal` and reads only that person's files, so an id
of anyone else's row raises ``DoesNotExist`` (404, never 403: the portal does not confirm
that someone else's record exists).

Data minimization: patients see the patient share and what they paid, never payer shares,
coverage rules or claim states; approved lab results only (the current approved version,
flagged when it amends an earlier one), never drafts; no staff-internal notes.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Prefetch, QuerySet
from django.utils import timezone

from apps.billing import services as billing
from apps.billing.models import DocumentStatus, Invoice
from apps.core.models import CenterProfile, DoctorProfile, User
from apps.lab.models import LabTest, ResultStatus, ResultValue, ResultVersion
from apps.orders.models import FulfilmentStatus, ServiceLine
from apps.patients.models import Patient
from apps.payments import services as payments
from apps.payments.models import Allocation, Payment
from apps.portal import conf
from apps.portal.services import PortalPrincipal, bookable_doctor
from apps.visits import services as visits
from apps.visits.models import Appointment, AppointmentStatus, DoctorSchedule
from domain import portal as dportal
from domain.money import ZERO, money
from domain.payments import Verification

__all__ = [
    "appointment",
    "appointments",
    "balance",
    "booking_days",
    "booking_doctors",
    "booking_slots",
    "invoice_detail",
    "invoices",
    "me",
    "prescriptions",
    "receipt_detail",
    "receipts",
    "result_detail",
    "results",
    "summary",
]

_ABNORMAL = frozenset({"low", "high", "critical_low", "critical_high", "abnormal"})
_RECENT_LIMIT = 50


def _m(value: Decimal) -> str:
    return format(money(value), "f")


def _names(user: User | None) -> dict[str, str] | None:
    if user is None:
        return None
    return {"name_ar": user.display_name_ar, "name_en": user.display_name_en}


def _doctor_json(doctor: DoctorProfile) -> dict[str, Any]:
    return {
        "id": doctor.pk,
        "name_ar": doctor.user.display_name_ar,
        "name_en": doctor.user.display_name_en,
        "specialty_ar": doctor.specialty_ar,
        "specialty_en": doctor.specialty_en,
        "department_ar": doctor.department.name_ar,
        "department_en": doctor.department.name_en,
    }


# --- profile and home ----------------------------------------------------------------------


def me(principal: PortalPrincipal) -> dict[str, Any]:
    p = principal.person()
    return {
        "file_no": p.file_no,
        "full_name_ar": p.full_name_ar,
        "full_name_en": p.full_name_en,
        "sex": p.sex,
        "date_of_birth": p.date_of_birth,
        "phone_masked": dportal.mask_phone(p.phone_norm or p.phone),
        "idle_seconds": int(conf.session_idle().total_seconds()),
    }


def summary(principal: PortalPrincipal) -> dict[str, Any]:
    """The home cards: the next appointment, the latest results and the balance."""
    upcoming = appointments(principal)["upcoming"]
    return {
        "next_appointment": upcoming[0] if upcoming else None,
        "latest_results": results(principal)[:3],
        "balance": balance(principal),
    }


# --- appointments --------------------------------------------------------------------------


def _appointment_rows(files: Iterable[int]) -> QuerySet[Appointment]:
    return Appointment.objects.filter(patient_id__in=list(files)).select_related(
        "doctor__user", "doctor__department", "department"
    )


def _appointment_json(a: Appointment, *, now: datetime) -> dict[str, Any]:
    rules = conf.booking_rules()
    booked = a.status == AppointmentStatus.BOOKED
    return {
        "id": a.pk,
        "starts_at": a.starts_at,
        "ends_at": a.ends_at,
        "status": a.status,
        "doctor": _doctor_json(a.doctor),
        "can_cancel": dportal.can_cancel(a.starts_at, booked=booked, now=now, rules=rules),
        "cancel_until": a.starts_at - rules.cancel_cutoff if booked else None,
    }


def appointment(principal: PortalPrincipal, appointment_id: int) -> dict[str, Any]:
    """Raises: Appointment.DoesNotExist (not the person's appointment: 404)."""
    row = _appointment_rows(principal.file_ids()).get(pk=appointment_id)
    return _appointment_json(row, now=timezone.now())


def appointments(principal: PortalPrincipal) -> dict[str, Any]:
    """Upcoming bookings (soonest first) and the last 20 past or closed ones."""
    now = timezone.now()
    rows = _appointment_rows(principal.file_ids())
    upcoming = rows.filter(status=AppointmentStatus.BOOKED, ends_at__gt=now).order_by(
        "starts_at", "id"
    )
    past = rows.exclude(pk__in=upcoming.values("pk")).order_by("-starts_at", "-id")[:20]
    return {
        "upcoming": [_appointment_json(a, now=now) for a in upcoming],
        "past": [_appointment_json(a, now=now) for a in past],
        "rules": {
            "max_open": conf.booking_rules().max_open,
            "cancel_cutoff_hours": int(conf.booking_rules().cancel_cutoff.total_seconds() // 3600),
            "horizon_days": conf.booking_rules().horizon_days,
        },
    }


def booking_doctors() -> list[dict[str, Any]]:
    """Doctors who take portal bookings: active, with an active weekly schedule."""
    doctors = (
        DoctorProfile.objects.filter(active=True, user__is_active=True, schedules__active=True)
        .select_related("user", "department")
        .distinct()
        .order_by("department__sort_order", "department__code", "user__username")
    )
    return [_doctor_json(d) for d in doctors]


def _bookable_starts(doctor: DoctorProfile, on: date, *, now: datetime) -> list[datetime]:
    return dportal.bookable(
        [start for start, _ in visits.available_slots(doctor, on)],
        now=now,
        today=timezone.localdate(),
        rules=conf.booking_rules(),
        day_of=lambda d: timezone.localtime(d).date(),
    )


def booking_days(doctor_id: int) -> list[date]:
    """The local days, from today to the booking horizon, with at least one bookable slot."""
    doctor = bookable_doctor(doctor_id)
    now = timezone.now()
    today = timezone.localdate()
    weekdays = set(
        DoctorSchedule.objects.filter(doctor=doctor, active=True).values_list("weekday", flat=True)
    )
    days = []
    for offset in range(conf.booking_rules().horizon_days + 1):
        on = today + timedelta(days=offset)
        if on.weekday() in weekdays and _bookable_starts(doctor, on, now=now):
            days.append(on)
    return days


def booking_slots(doctor_id: int, on: date) -> dict[str, Any]:
    doctor = bookable_doctor(doctor_id)
    starts = set(_bookable_starts(doctor, on, now=timezone.now()))
    slots = [
        {"starts_at": s, "ends_at": e} for s, e in visits.available_slots(doctor, on) if s in starts
    ]
    return {"doctor": _doctor_json(doctor), "day": on, "slots": slots}


# --- lab results ---------------------------------------------------------------------------


def _approved_versions(files: Iterable[int]) -> QuerySet[ResultVersion]:
    """The current approved version of each lab line of the person (never a draft, never a
    superseded version)."""
    return (
        ResultVersion.objects.filter(
            status=ResultStatus.APPROVED,
            result_set__service_line__visit__patient_id__in=list(files),
        )
        .exclude(result_set__service_line__fulfilment_status=FulfilmentStatus.CANCELLED)
        .select_related(
            "result_set__test__service",
            "result_set__service_line__visit__patient",
            "result_set__service_line__ordered_by",
        )
        .prefetch_related(
            Prefetch("values", queryset=ResultValue.objects.select_related("parameter"))
        )
    )


def _shown_value(v: ResultValue) -> str:
    if v.value_numeric is None:
        return v.value_text
    places = Decimal(1).scaleb(-v.parameter.decimals)
    return format(v.value_numeric.quantize(places), "f")


def _dec(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def _result_summary(v: ResultVersion) -> dict[str, Any]:
    line = v.result_set.service_line
    test: LabTest = v.result_set.test
    return {
        "line_id": line.pk,
        "test_name_ar": test.service.name_ar,
        "test_name_en": test.service.name_en,
        "ordered_at": line.ordered_at,
        "approved_at": v.approved_at,
        "amended": v.amends_id is not None,
        "abnormal": any(val.flag in _ABNORMAL for val in v.values.all()),
    }


def results(principal: PortalPrincipal) -> list[dict[str, Any]]:
    versions = _approved_versions(principal.file_ids()).order_by("-approved_at", "-id")
    return [_result_summary(v) for v in versions[:_RECENT_LIMIT]]


def _center() -> dict[str, str]:
    c = CenterProfile.load()
    return {"name_ar": c.name_ar, "name_en": c.name_en, "address": c.address, "phone": c.phone}


def _patient_head(p: Patient) -> dict[str, Any]:
    return {
        "file_no": p.file_no,
        "full_name_ar": p.full_name_ar,
        "full_name_en": p.full_name_en,
        "sex": p.sex,
        "date_of_birth": p.date_of_birth,
    }


def result_detail(principal: PortalPrincipal, line_id: int) -> dict[str, Any]:
    """One approved result with its values, for viewing and printing.

    Raises:
        ResultVersion.DoesNotExist: not the person's line, or no approved version yet (404).
    """
    v = _approved_versions(principal.file_ids()).get(result_set__service_line_id=line_id)
    line: ServiceLine = v.result_set.service_line
    values = sorted(v.values.all(), key=lambda x: (x.parameter.sort_order, x.parameter.code, x.pk))
    return {
        **_result_summary(v),
        "center": _center(),
        "patient": _patient_head(line.visit.patient),
        "visit_number": line.visit.number,
        "ordered_by": _names(line.ordered_by),
        "comment": v.comment,
        "values": [
            {
                "parameter_code": val.parameter.code,
                "name_ar": val.parameter.name_ar,
                "name_en": val.parameter.name_en,
                "value": _shown_value(val),
                "unit": val.unit or val.parameter.unit,
                "reference_low": _dec(val.reference_low),
                "reference_high": _dec(val.reference_high),
                "reference_text": val.reference_text,
                "flag": val.flag,
            }
            for val in values
        ],
    }


# --- prescriptions and instructions --------------------------------------------------------


def _dispense_state(line: ServiceLine) -> str:
    if line.fulfilment_status == FulfilmentStatus.PERFORMED:
        return "dispensed"
    if line.fulfilment_status == FulfilmentStatus.IN_PROGRESS:
        return "partly_dispensed"
    return "not_dispensed"


def prescriptions(principal: PortalPrincipal) -> dict[str, Any]:
    """Prescribed drugs with how to take them (newest visit first), and the preparation
    instructions of lab tests still to be done."""
    files = principal.file_ids()
    drug_lines = (
        ServiceLine.objects.filter(
            visit__patient_id__in=files, kind="drug", prescription__isnull=False
        )
        .exclude(fulfilment_status=FulfilmentStatus.CANCELLED)
        .select_related("service", "prescription", "visit", "ordered_by")
        .order_by("-ordered_at", "-id")[:_RECENT_LIMIT]
    )
    visits_out: dict[int, dict[str, Any]] = {}
    for line in drug_lines:
        rx = line.prescription
        entry = visits_out.setdefault(
            line.visit_id,
            {
                "visit_number": line.visit.number,
                "date": timezone.localdate(line.visit.created_at),
                "prescriber": _names(line.ordered_by),
                "items": [],
            },
        )
        entry["items"].append(
            {
                "line_id": line.pk,
                "name_ar": line.service.name_ar,
                "name_en": line.service.name_en,
                "dose": rx.dose,
                "route": rx.route,
                "frequency_code": rx.frequency_code,
                "frequency_per_day": (
                    None if rx.frequency_per_day is None else _dec(rx.frequency_per_day)
                ),
                "duration_days": rx.duration_days,
                "as_needed": rx.as_needed,
                "instructions": rx.instructions,
                "quantity": int(line.quantity),
                "state": _dispense_state(line),
            }
        )
    since = timezone.now() - timedelta(days=30)
    open_lab = (
        ServiceLine.objects.filter(
            visit__patient_id__in=files,
            kind="lab",
            ordered_at__gte=since,
            fulfilment_status__in=[FulfilmentStatus.PENDING, FulfilmentStatus.IN_PROGRESS],
        )
        .select_related("service")
        .order_by("-ordered_at", "-id")
    )
    tests = {
        t.service_id: t
        for t in LabTest.objects.filter(service_id__in=[ln.service_id for ln in open_lab])
    }
    instructions = []
    for line in open_lab:
        test = tests.get(line.service_id)
        if test is None or not (test.instructions_ar or test.instructions_en):
            continue
        instructions.append(
            {
                "line_id": line.pk,
                "test_name_ar": line.service.name_ar,
                "test_name_en": line.service.name_en,
                "instructions_ar": test.instructions_ar,
                "instructions_en": test.instructions_en,
                "ordered_at": line.ordered_at,
            }
        )
    return {"visits": list(visits_out.values()), "lab_instructions": instructions}


# --- invoices, receipts, balance -----------------------------------------------------------


def _approved_invoices(files: Iterable[int]) -> QuerySet[Invoice]:
    return Invoice.objects.filter(
        patient_id__in=list(files), status=DocumentStatus.APPROVED
    ).select_related("visit")


def _invoice_json(inv: Invoice, pos: Any) -> dict[str, Any]:
    return {
        "id": inv.pk,
        "number": inv.number or "",
        "date": timezone.localdate(inv.approved_at) if inv.approved_at else None,
        "visit_number": inv.visit.number,
        "patient_due": _m(pos.patient_due),
        "paid": _m(pos.applied),
        "outstanding": _m(pos.outstanding),
    }


def invoices(principal: PortalPrincipal) -> list[dict[str, Any]]:
    rows = list(
        _approved_invoices(principal.file_ids()).order_by("-approved_at", "-id")[:_RECENT_LIMIT]
    )
    positions = billing.invoice_positions(rows)
    return [_invoice_json(inv, positions[inv.pk]) for inv in rows]


def invoice_detail(principal: PortalPrincipal, invoice_id: int) -> dict[str, Any]:
    """Raises: Invoice.DoesNotExist (not the person's approved invoice: 404)."""
    inv = _approved_invoices(principal.file_ids()).get(pk=invoice_id)
    pos = billing.invoice_position(inv)
    return {
        **_invoice_json(inv, pos),
        "center": _center(),
        "lines": [
            {
                "description_ar": il.description_ar,
                "description_en": il.description_en,
                "quantity": int(il.quantity),
                "patient_share": _m(il.patient_share),
            }
            for il in inv.lines.filter(frozen=True).order_by("line_no")
        ],
        "receipts": [
            {
                "id": p.pk,
                "number": p.number,
                "date": timezone.localdate(p.created_at),
                "amount": _m(a),
            }
            for p, a in _receipts_of(inv)
        ],
    }


def _receipts_of(inv: Invoice) -> list[tuple[Payment, Decimal]]:
    totals: dict[int, Decimal] = {}
    for payment_id, amount in Allocation.objects.filter(invoice=inv).values_list(
        "payment_id", "amount"
    ):
        totals[payment_id] = totals.get(payment_id, ZERO) + amount
    shown = {pid: amt for pid, amt in totals.items() if amt != 0}
    rows = Payment.objects.filter(pk__in=shown, reversal_of__isnull=True).order_by(
        "created_at", "id"
    )
    return [(p, shown[p.pk]) for p in rows]


def _receipt_rows(files: Iterable[int]) -> QuerySet[Payment]:
    # Reversal rows are the center's own bookkeeping; the original then shows as void.
    return Payment.objects.filter(patient_id__in=list(files), reversal_of__isnull=True)


def _receipt_json(p: Payment, reversed_ids: set[int]) -> dict[str, Any]:
    return {
        "id": p.pk,
        "number": p.number,
        "date": timezone.localdate(p.created_at),
        "amount": _m(p.amount),
        "method": p.method,
        "status": str(
            dportal.public_receipt_status(
                Verification(p.verification), reversed_=p.pk in reversed_ids, is_reversal=False
            )
        ),
    }


def _reversed(ids: Iterable[int]) -> set[int]:
    return set(
        Payment.objects.filter(reversal_of_id__in=list(ids)).values_list(
            "reversal_of_id", flat=True
        )
    )


def receipts(principal: PortalPrincipal) -> list[dict[str, Any]]:
    rows = list(_receipt_rows(principal.file_ids()).order_by("-created_at", "-id")[:_RECENT_LIMIT])
    reversed_ids = _reversed(p.pk for p in rows)
    return [_receipt_json(p, reversed_ids) for p in rows]


def receipt_detail(principal: PortalPrincipal, payment_id: int) -> dict[str, Any]:
    """Raises: Payment.DoesNotExist (not the person's receipt: 404)."""
    p = _receipt_rows(principal.file_ids()).get(pk=payment_id)
    per_invoice: dict[int, Decimal] = {}
    for inv_id, amount in Allocation.objects.filter(payment=p).values_list("invoice_id", "amount"):
        per_invoice[inv_id] = per_invoice.get(inv_id, ZERO) + amount
    numbers = dict(
        Invoice.objects.filter(pk__in=[k for k, v in per_invoice.items() if v != 0]).values_list(
            "pk", "number"
        )
    )
    applied = sum((v for v in per_invoice.values()), ZERO)
    return {
        **_receipt_json(p, _reversed([p.pk])),
        "center": _center(),
        "invoices": [
            {"id": inv_id, "number": numbers[inv_id] or "", "amount": _m(per_invoice[inv_id])}
            for inv_id in sorted(numbers)
        ],
        "to_credit": _m(max(p.amount - applied, ZERO)),
    }


def balance(principal: PortalPrincipal) -> dict[str, Any]:
    """What the person owes and holds (every merged file counts, FEATURES 1.5)."""
    b = payments.patient_balance(principal.person())
    return {
        "outstanding": _m(b.outstanding),
        "credit": _m(b.spendable),
        "pending": _m(b.pending),
        "open_invoices": len(b.invoices),
    }
