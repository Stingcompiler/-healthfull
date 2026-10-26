"""Printed prescription and referral letter (FEATURES 3.5, 3.9; inspection F03).

Both are A4 documents the doctor hands to the patient: the center's identity (CenterProfile)
and the document's print template (header, footer, logo switch; ``core.PrintTemplate``), the
patient, the visit and its doctor, and the clinical content. **No prices**: the doctor never
sees one (FEATURES 3.8) and the documents leave the center.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from apps.clinical import schemas as s
from apps.clinical.models import Diagnosis, Referral, ReferralStatus
from apps.clinical.services import active_allergies
from apps.core.models import CenterProfile, PaperSize, PrintDocument, PrintTemplate
from apps.orders.models import FulfilmentStatus, ServiceLine
from apps.visits.models import Visit
from domain.errors import DomainError

__all__ = ["prescription_print", "referral_print"]


def _center() -> dict[str, Any]:
    c = CenterProfile.load()
    return {
        "name_ar": c.name_ar,
        "name_en": c.name_en,
        "address": c.address,
        "phone": c.phone,
        "has_logo": bool(c.logo),
    }


def _template(document: str) -> dict[str, Any]:
    row = PrintTemplate.objects.filter(document=document, paper=PaperSize.A4, active=True).first()
    return {
        "show_logo": row.show_logo if row else True,
        "header_ar": row.header_ar if row else "",
        "header_en": row.header_en if row else "",
        "footer_ar": row.footer_ar if row else "",
        "footer_en": row.footer_en if row else "",
    }


def _patient(visit: Visit) -> dict[str, Any]:
    p = visit.patient
    return {
        "file_no": p.file_no,
        "full_name_ar": p.full_name_ar,
        "full_name_en": p.full_name_en,
        "sex": p.sex,
        "date_of_birth": p.date_of_birth,
        "dob_is_estimated": p.dob_is_estimated,
    }


def _common(visit: Visit, document: str) -> dict[str, Any]:
    return {
        "center": _center(),
        "template": _template(document),
        "patient": _patient(visit),
        "allergies": [s.allergy_chip(a) for a in active_allergies(visit.patient)],
        "visit_number": visit.number,
        "visit_date": timezone.localdate(visit.created_at),
        "department": s.department_ref(visit.department),
        "doctor": s.doctor_ref(visit.doctor),
        "diagnoses": [
            s.diagnosis_out(d)
            for d in Diagnosis.objects.filter(visit=visit)
            .select_related("icd10", "recorded_by")
            .order_by("kind", "recorded_at", "id")
        ],
        "printed_at": timezone.now(),
    }


def _visit(visit_id: int) -> Visit:
    return Visit.objects.select_related("patient", "department", "doctor__user").get(pk=visit_id)


def prescription_print(visit_id: int) -> dict[str, Any]:
    """The visit's prescribed drugs (not cancelled) with how to take them.

    Raises:
        Visit.DoesNotExist: 404.
        DomainError: ``NO_PRESCRIPTION`` when the visit has no prescribed drug to print.
    """
    visit = _visit(visit_id)
    lines = (
        ServiceLine.objects.filter(visit=visit, kind="drug", prescription__isnull=False)
        .exclude(fulfilment_status=FulfilmentStatus.CANCELLED)
        .select_related("service", "prescription", "ordered_by")
        .order_by("ordered_at", "id")
    )
    items = []
    prescriber = None
    for line in lines:
        rx = line.prescription
        prescriber = prescriber or line.ordered_by
        items.append(
            {
                "line_id": line.pk,
                "name_ar": line.service.name_ar,
                "name_en": line.service.name_en,
                "dose": rx.dose,
                "route": rx.route,
                "frequency_code": rx.frequency_code,
                "frequency_per_day": (
                    None if rx.frequency_per_day is None else str(rx.frequency_per_day.normalize())
                ),
                "duration_days": rx.duration_days,
                "as_needed": rx.as_needed,
                "instructions": rx.instructions,
                "quantity": int(line.quantity),
            }
        )
    if not items:
        raise DomainError("NO_PRESCRIPTION", "This visit has no prescribed drug to print")
    return {
        **_common(visit, PrintDocument.PRESCRIPTION),
        "prescriber": s.user_ref(prescriber),
        "items": items,
    }


def referral_print(referral_id: int) -> dict[str, Any]:
    """A referral letter. A cancelled referral is never printed.

    Raises:
        Referral.DoesNotExist: 404.
        DomainError: ``REFERRAL_CLOSED`` for a cancelled referral.
    """
    referral = Referral.objects.select_related(
        "to_department", "to_doctor__user", "referred_by"
    ).get(pk=referral_id)
    if referral.status == ReferralStatus.CANCELLED:
        raise DomainError("REFERRAL_CLOSED", "A cancelled referral is not printed")
    visit = _visit(referral.visit_id)
    return {
        **_common(visit, PrintDocument.REFERRAL),
        "referral": s.referral_out(referral),
    }
