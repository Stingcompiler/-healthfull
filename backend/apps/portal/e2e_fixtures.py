"""e2e builders of the patient portal (``manage.py e2e_fixture``, test databases only).

``portal_patient``: one call builds what every portal screen shows for a new patient, through
the services as the seed users: a paid visit with a CBC (approved by ``labsup``) and a malaria
test (entered, not approved: it must never reach the portal), a prescription with dosing
instructions, optionally an upcoming appointment, and a portal access code printed for the
receipt by ``cashier``. Returns the file number, phone and code to sign in with, and ids.

Times are relative to now and slots come from the doctor's schedule, so the data does not
depend on the hour the suite runs (an appointment is booked from tomorrow on).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from apps.core.e2e.fixtures import Json, Params, fixture, run_nested
from apps.core.models import User
from apps.core.services import require_permission
from apps.patients.models import Patient
from apps.payments.models import Payment
from apps.portal import queries, services
from apps.visits import services as visits
from apps.visits.models import Appointment
from domain.errors import DomainError


def _book_upcoming(patient_id: int, doctor_username: str, actor: User) -> Appointment:
    doctor = User.objects.get(username=doctor_username).doctor_profile
    tomorrow = timezone.localdate() + timedelta(days=1)
    for day in queries.booking_days(doctor.pk):
        if day < tomorrow:
            continue
        slots = queries.booking_slots(doctor.pk, day)["slots"]
        if slots:
            return visits.book_appointment(
                doctor=doctor,
                starts_at=slots[0]["starts_at"],
                actor=actor,
                patient=Patient.objects.get(pk=patient_id),
            )
    raise DomainError("FIXTURE_PARAM_INVALID", f"doctor: {doctor_username} has no free slot")


@fixture(
    "portal_patient",
    summary=(
        "A new patient (`patient_fields` override) with a paid visit: CBC approved, malaria "
        "entered but not approved, a prescription, and a portal access code for the receipt "
        "(`code` false to skip). `appointment` true books the next free slot of `doctor` "
        "from tomorrow on. Returns file_no, phone, code, line ids, invoice, payment, token."
    ),
    params=("patient_fields", "appointment", "doctor", "code"),
)
def portal_patient(p: Params) -> Json:
    fields: dict[str, Any] = {"sex": "female", "date_of_birth": "1990-05-01"}
    fields.update(p.mapping("patient_fields"))
    order = run_nested("lab_order", {"tests": ["LAB-CBC", "LAB-BFMP"], "patient_fields": fields})
    patient = order["patient"]
    visit = order["visit"]
    cbc, bfmp = order["lab_lines"]
    run_nested(
        "order",
        {
            "visit": visit["id"],
            "items": [
                {
                    "service": "DRG-AMOX500",
                    "prescription": {
                        "dose": "500 mg",
                        "dose_quantity": 1,
                        "frequency_code": "TID",
                        "frequency_per_day": 3,
                        "duration_days": 7,
                        "instructions": "After meals",
                    },
                }
            ],
        },
    )
    approved = run_nested("lab_progress", {"line": cbc["id"], "stage": "approved"})
    draft = run_nested(
        "lab_progress", {"line": bfmp["id"], "stage": "entered", "values": {"MP": "positive"}}
    )
    payment = (
        Payment.objects.filter(patient_id=patient["id"], reversal_of__isnull=True)
        .order_by("-id")
        .first()
    )
    if payment is None:  # pragma: no cover - lab_order pays unless told not to
        raise DomainError("FIXTURE_PARAM_INVALID", "the visit has no payment")
    result: Json = {
        "patient": {
            "id": patient["id"],
            "file_no": patient["file_no"],
            "phone": patient["phone"],
        },
        "visit": {"id": visit["id"], "number": visit["number"]},
        "approved_line": approved["line"],
        "draft_line": draft["line"],
        "invoice": {"id": order["invoice"]["id"], "number": order["invoice"]["number"]},
        "payment": {"id": payment.pk, "number": payment.number},
        "verify_token": services.receipt_verify_token(payment.number),
        "code": None,
        "appointment": None,
    }
    if p.flag("code", True):
        cashier = p.actor("cashier")
        require_permission(cashier, "portal.issue_access_code")
        issued = services.issue_access_code(payment.pk, actor=cashier)
        result["code"] = issued.code
    if p.flag("appointment", False):
        reception = User.objects.get(username="reception")
        require_permission(reception, "visits.manage_appointments")
        booked = _book_upcoming(patient["id"], p.text("doctor", "doctor"), reception)
        result["appointment"] = {"id": booked.pk, "starts_at": booked.starts_at.isoformat()}
    return result


@fixture(
    "portal_code",
    summary="A fresh portal access code for the patient of receipt `payment` (id), as `cashier`.",
    params=("payment",),
)
def portal_code(p: Params) -> Json:
    cashier = p.actor("cashier")
    require_permission(cashier, "portal.issue_access_code")
    payment_id = p.integer("payment")
    if payment_id is None:
        raise DomainError("FIXTURE_PARAM_INVALID", "payment: required")
    issued = services.issue_access_code(payment_id, actor=cashier)
    return {"code": issued.code, "file_no": issued.file_no}
