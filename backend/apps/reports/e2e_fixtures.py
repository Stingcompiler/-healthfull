"""e2e builders of the reports module (``manage.py e2e_fixture``, test databases only).

``reports_day``: one day of activity with exact figures for the report specs, in one call. The
e2e database is shared by every spec, so the activity is made traceable: it belongs to a new
doctor (``rptdoc<n>``, GEN clinic, GEN consultation), whose row in the revenue report's "by
doctor" section shows exactly this call's money, and to one new patient and visit:

* consultation ``CONS-GEN`` 15,000: invoiced and paid in cash, not performed;
* ``PRC-ECG`` 10,000 (1,000 hardship discount approved by the cashier supervisor),
  ``PRC-INJ`` 2,000 and ``LAB-CBC`` 12,000: invoiced together (23,000 to pay) and paid by a bank
  transfer left pending; the injection is performed, ECG and CBC are paid and not performed;
* ``PRC-DRESS`` ordered afterwards and never invoiced.

So for the doctor: gross 39,000, discount 1,000, net 38,000; collected in cash 15,000;
pending 23,000. ``day`` is the local date the activity was booked: specs pin their report
dates to it, so a run that crosses midnight still reads the right day.

Every step goes through the services as the seed user the matching screen would act as
(reception, doctor, cashier, cashier supervisor, nurse), after that endpoint's permission check.
"""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from apps.billing import services as billing
from apps.billing.models import Invoice
from apps.catalog.models import Service
from apps.core.e2e.fixtures import Json, Params, fixture, run_nested
from apps.core.models import Department, DoctorProfile, Role, User, UserRole
from apps.core.services import require_permission
from apps.orders import services as orders
from apps.orders.models import ServiceLine

PREFIX = "rptdoc"


def _doctor() -> DoctorProfile:
    """A new GEN doctor (written like the base seed writes its doctors)."""
    n = User.objects.filter(username__startswith=PREFIX).count() + 1
    while User.objects.filter(username=f"{PREFIX}{n}").exists():
        n += 1
    user = User(
        username=f"{PREFIX}{n}",
        full_name_ar=f"طبيب التقارير {n}",
        full_name_en=f"Report Doctor {n}",
        must_change_password=False,
    )
    user.set_unusable_password()
    user.save()
    UserRole.objects.create(user=user, role=Role.objects.get(code="doctor"))
    return DoctorProfile.objects.create(
        user=user,
        department=Department.objects.get(code="GEN"),
        consultation_service=Service.objects.get(code="CONS-GEN"),
        specialty_ar="طب عام",
        specialty_en="General practice",
    )


def _line(visit_number: str, code: str) -> ServiceLine:
    return ServiceLine.objects.get(visit__number=visit_number, service__code=code)


@fixture(
    "reports_day",
    summary=(
        "One day of traceable activity for the report specs: a new doctor's visit with cash, "
        "a discount, a pending transfer, paid-not-performed and requested-not-invoiced lines; "
        "returns the day, the references and the expected figures."
    ),
    params=(),
)
def reports_day(p: Params) -> Json:
    supervisor = p.user("supervisor", "cashsup")
    nurse = p.user("nurse", "nurse")
    doctor = _doctor()
    username = doctor.user.username

    patient = run_nested("patient", {})["patient"]
    visit = run_nested("visit", {"patient": patient["file_no"], "doctor": username})["visit"]
    run_nested(
        "order",
        {
            "visit": visit["number"],
            "items": [{"service": "PRC-ECG"}, {"service": "PRC-INJ"}, {"service": "LAB-CBC"}],
            "as": username,
        },
    )
    run_nested("open_shift", {"if_open": "reuse"})

    consultation = run_nested(
        "invoice", {"visit": visit["number"], "services": ["CONS-GEN"], "approve": True}
    )["invoice"]
    cash = run_nested("pay", {"invoice": consultation["number"], "method": "cash"})["payment"]

    draft_ref = run_nested(
        "invoice", {"visit": visit["number"], "services": ["PRC-ECG", "PRC-INJ", "LAB-CBC"]}
    )["invoice"]
    draft = Invoice.objects.get(pk=draft_ref["id"])
    require_permission(supervisor, "billing.apply_discount")
    billing.apply_discount(
        draft.lines.get(service__code="PRC-ECG"),
        actor=supervisor,
        reason="HARDSHIP",
        amount=Decimal("1000.00"),
    )
    services = run_nested("approve_invoice", {"invoice": draft_ref["id"]})["invoice"]
    transfer = run_nested("pay", {"invoice": services["number"], "method": "bank_transfer"})[
        "payment"
    ]

    require_permission(nurse, "orders.perform_procedure")
    orders.perform_line(_line(visit["number"], "PRC-INJ"), nurse)
    run_nested(
        "order", {"visit": visit["number"], "items": [{"service": "PRC-DRESS"}], "as": username}
    )

    return {
        "day": timezone.localdate().isoformat(),
        "doctor": {
            "id": doctor.pk,
            "user_id": doctor.user_id,
            "username": username,
            "name_ar": doctor.user.full_name_ar,
            "name_en": doctor.user.full_name_en,
        },
        "patient": {"file_no": patient["file_no"]},
        "visit": {"number": visit["number"]},
        "cash": {"number": cash["number"], "amount": cash["amount"]},
        "transfer": {"number": transfer["number"], "amount": transfer["amount"]},
        "expected": {
            "gross": "39000.00",
            "discount": "1000.00",
            "net": "38000.00",
            "cash": "15000.00",
            "pending": "23000.00",
            "paid_not_performed": {
                "CONS-GEN": "15000.00",
                "PRC-ECG": "9000.00",
                "LAB-CBC": "12000.00",
            },
            "requested_not_invoiced": ["PRC-DRESS"],
        },
    }
