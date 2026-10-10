"""One day at the center through the real services, for the report tests.

Every figure below is what the reports must show; the ledger is checked against them in
``test_reconciliation``. All of it happens today (Africa/Khartoum).

* OPD (doctor, consultation 5,000; injection 2,000) and LAB (CBC 10,000; insurer pays 70%).
* Patient A (cash): consultation invoiced and paid in cash 5,000. CBC + injection invoiced
  12,000 with a 500 hardship discount on the injection (approved by the supervisor), paid by a
  6,000 bank transfer (left pending) and 5,500 cash. The CBC is performed; the injection is
  paid and not performed. The consultation is then cancelled (equipment down): credit note
  5,000, refund approved by the accountant and paid in cash.
* Patient B (insured, no doctor, LAB): CBC invoiced 10,000 = 7,000 payer + 3,000 patient, paid
  by a 3,000 transfer the supervisor confirms. Not performed. An injection is ordered and never
  invoiced; another is refused by the patient (cancelled unbilled).
* Patient C: an injection performed before payment under the supervisor's emergency
  authorization (never invoiced).
* The cashier's shift (float 1,000) closes 100 short.

Totals: gross 27,000; discount 500; credited 5,000; net 21,500 (OPD 1,500, LAB 20,000);
payer share 7,000; cash 10,500; confirmed transfers 3,000; pending 6,000; refunds 5,000;
expected cash 6,500, counted 6,400, variance -100.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from apps.billing import services as billing
from apps.billing.models import Invoice
from apps.catalog.models import Payer, Service
from apps.core.models import Department, DoctorProfile, Policy, Role, User
from apps.core.tests import builders as b
from apps.orders import services as orders
from apps.orders.models import ServiceLine
from apps.patients import services as patients
from apps.patients.models import Patient
from apps.payments import services as pay
from apps.payments.models import Bank, Payment, Refund, Shift
from apps.payments.tests import fin
from apps.visits import services as visits
from apps.visits.models import Visit

D = Decimal
_n = itertools.count(1)


@dataclass
class Day:
    receptionist: User
    cashier: User
    supervisor: User
    accountant: User
    manager: User
    nurse: User
    lab_tech: User
    opd: Department
    lab: Department
    doctor: DoctorProfile
    consult: Service
    cbc: Service
    injection: Service
    insurer: Payer
    shift: Shift
    patient_a: Patient
    patient_b: Patient
    patient_c: Patient
    visit_a: Visit
    visit_b: Visit
    visit_c: Visit
    inv_a1: Invoice
    inv_a2: Invoice
    inv_b: Invoice
    transfer_a: Payment
    transfer_b: Payment
    refund: Refund
    lab_a: ServiceLine
    inj_a: ServiceLine
    cbc_b: ServiceLine
    inj_b_open: ServiceLine
    inj_b_refused: ServiceLine
    inj_c: ServiceLine


def _person(sex: str = "female", **names: Any) -> patients.PatientData:
    i = next(_n)
    return patients.PatientData(
        sex=sex,
        full_name_ar=names.get("ar", f"مريضة اختبار {i}"),
        full_name_en=names.get("en", f"Report Patient {i}"),
        phone=f"0912{i:06d}",
    )


def staff() -> dict[str, User]:
    return {
        role: fin.staff(role)
        for role in (
            "receptionist",
            "cashier",
            "cashier_supervisor",
            "accountant",
            "manager",
            "nurse",
            "lab_tech",
        )
    }


def build_day() -> Day:
    fin.seed()
    Policy.objects.update(allow_partial_payment=True)
    people = staff()
    receptionist, cashier = people["receptionist"], people["cashier"]
    supervisor, accountant = people["cashier_supervisor"], people["accountant"]

    opd = b.department(f"OPD{next(_n)}")
    lab = b.department(f"LAB{next(_n)}")
    consult = fin.priced("consultation", "5000.00", department=opd)
    doctor = b.doctor(opd)
    doctor.consultation_service = consult
    doctor.save()
    doctor.user.user_roles.create(role=Role.objects.get(code="doctor"))
    cbc = fin.priced("lab", "10000.00", department=lab)
    injection = fin.priced("procedure", "2000.00", department=opd)
    insurer = fin.payer(percent="70.00", service_kind="lab")
    bok = Bank.objects.get(code="BOK")

    shift = pay.open_shift(cashier, D("1000.00"))

    # Patient A: cash.
    patient_a = patients.register_patient(_person(), actor=receptionist)
    visit_a = visits.create_visit(patient=patient_a, actor=receptionist, doctor=doctor)
    inv_a1 = fin.invoice(visit_a, cashier)
    pay.record_payment(shift, patient_a, "cash", D("5000.00"), actor=cashier, auto=True)
    lab_a, inj_a = fin.order(visit_a, doctor.user, cbc, injection)
    draft = billing.create_draft_invoice(visit_a, cashier)
    billing.apply_discount(
        draft.lines.get(service_line=inj_a),
        actor=supervisor,
        reason="HARDSHIP",
        amount=D("500.00"),
    )
    inv_a2 = billing.approve_invoice(draft, actor=cashier)
    transfer_a = pay.record_payment(
        shift,
        patient_a,
        "bank_transfer",
        D("6000.00"),
        actor=cashier,
        bank=bok,
        reference=f"FT-A-{next(_n)}",
        allocations=[(inv_a2, D("6000.00"))],
    )
    pay.record_payment(shift, patient_a, "cash", D("5500.00"), actor=cashier, auto=True)
    orders.start_line(lab_a, people["lab_tech"])
    orders.perform_line(lab_a, people["lab_tech"])

    # Patient B: insured, LAB only.
    patient_b = patients.register_patient(_person("male"), actor=receptionist)
    cover = patients.add_coverage(
        patient_b, payer=insurer, actor=receptionist, card_number=f"C-{next(_n)}"
    )
    visit_b = visits.create_visit(
        patient=patient_b, actor=receptionist, department=lab, coverage=cover
    )
    (cbc_b,) = fin.order(visit_b, doctor.user, cbc)
    inv_b = fin.invoice(visit_b, cashier, [cbc_b])
    transfer_b = pay.record_payment(
        shift,
        patient_b,
        "bank_transfer",
        D("3000.00"),
        actor=cashier,
        bank=bok,
        reference=f"FT-B-{next(_n)}",
        allocations=[(inv_b, D("3000.00"))],
    )
    pay.confirm_transfer(transfer_b, actor=supervisor, note="seen on the statement")
    inj_b_open, inj_b_refused = fin.order(visit_b, doctor.user, injection, injection)
    orders.cancel_line(inj_b_refused, "PATIENT_REFUSED", cashier)

    # Patient C: performed first under an emergency authorization.
    patient_c = patients.register_patient(_person(), actor=receptionist)
    visit_c = visits.create_visit(patient=patient_c, actor=receptionist, department=opd)
    (inj_c,) = fin.order(visit_c, doctor.user, injection)
    orders.authorize_perform_first(
        [inj_c], actor=supervisor, reason="EMERGENCY", kind="emergency", note="collapsed"
    )
    orders.perform_line(inj_c, people["nurse"])

    # The consultation cannot happen: credited, refunded in cash.
    fee = ServiceLine.objects.get(visit=visit_a, service=consult)
    orders.cancel_line(fee, "EQUIPMENT_DOWN", supervisor)
    refund = Refund.objects.get(patient=patient_a)
    pay.approve_refund(refund, actor=accountant)
    refund = pay.pay_refund(refund, actor=cashier)

    shift = pay.close_shift(
        shift, D("6400.00"), actor=cashier, reason="COUNTING_ERROR", note="recount"
    )
    for obj in (transfer_a, transfer_b):
        obj.refresh_from_db()
    return Day(
        receptionist=receptionist,
        cashier=cashier,
        supervisor=supervisor,
        accountant=accountant,
        manager=people["manager"],
        nurse=people["nurse"],
        lab_tech=people["lab_tech"],
        opd=opd,
        lab=lab,
        doctor=doctor,
        consult=consult,
        cbc=cbc,
        injection=injection,
        insurer=insurer,
        shift=shift,
        patient_a=patient_a,
        patient_b=patient_b,
        patient_c=patient_c,
        visit_a=visit_a,
        visit_b=visit_b,
        visit_c=visit_c,
        inv_a1=inv_a1,
        inv_a2=inv_a2,
        inv_b=inv_b,
        transfer_a=transfer_a,
        transfer_b=transfer_b,
        refund=refund,
        lab_a=lab_a,
        inj_a=inj_a,
        cbc_b=cbc_b,
        inj_b_open=inj_b_open,
        inj_b_refused=inj_b_refused,
        inj_c=inj_c,
    )
