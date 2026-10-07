"""The whole FLOW.md cycle through the services, with the books checked at every step.

register -> visit (consultation line) -> consultation invoice and cash -> doctor queue ->
orders -> invoice with an insurance line split 7000/3000 -> pending transfer + cash ->
lines settled -> lab, nursing and pharmacy perform -> shift closed short -> the transfer is
rejected the next day (reversal in the supervisor's open shift, lines back to invoiced,
managers alerted) -> the patient pays again -> a paid line is cancelled (credit note,
de-allocation into patient credit, refund request) -> refund approved and paid in cash.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.billing import services as billing
from apps.core.models import Notification, Policy
from apps.core.tests import builders as b
from apps.ledger import services as ledger
from apps.ledger.models import JournalEntry
from apps.orders import services as orders
from apps.orders.models import ServiceLine
from apps.patients import services as patients
from apps.payments import services as pay
from apps.payments.models import Payment, Refund
from apps.payments.tests import fin
from apps.visits import services as visits
from apps.visits.models import QueueEntry

D = Decimal
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _seed() -> None:
    fin.seed()


def _state(line: ServiceLine) -> tuple[str, str]:
    line.refresh_from_db()
    return line.billing_status, line.fulfilment_status


def test_full_cycle_keeps_documents_and_ledger_in_step() -> None:
    receptionist = fin.staff("receptionist")
    cashier = fin.staff("cashier")
    cashier2 = fin.staff("cashier")
    supervisor = fin.staff("cashier_supervisor")
    manager = fin.staff("manager")
    nurse = fin.staff("nurse")
    pharmacist = fin.staff("pharmacist")
    lab_tech = fin.staff("lab_tech")

    clinic = b.department("OPD")
    lab_dept = b.department("LAB")
    consult = fin.priced("consultation", "5000.00", department=clinic)
    doctor = b.doctor(clinic)
    doctor.consultation_service = consult
    doctor.save()
    doctor.user.user_roles.create(role_id=fin.Role.objects.get(code="doctor").pk)
    cbc = fin.priced("lab", "10000.00", department=lab_dept)
    injection = fin.priced("procedure", "2000.00", department=clinic)
    dressing = fin.priced("procedure", "1500.00", department=clinic)
    paracetamol = fin.priced("drug", "50.00")
    insurer = fin.payer(percent="70.00", service_kind="lab")
    # Split tender (transfer + cash on one invoice) needs partial allocation: under the
    # default policy each payment must clear the invoice on its own.
    Policy.objects.update(allow_partial_payment=True)

    # 1. Registration and visit: the consultation line is requested automatically.
    patient = patients.register_patient(
        patients.PatientData(sex="female", full_name_ar="آمنة عثمان", phone="0912345678"),
        actor=receptionist,
    )
    cover = patients.add_coverage(patient, payer=insurer, actor=receptionist, card_number="C-77")
    visit = visits.create_visit(patient=patient, actor=receptionist, doctor=doctor, coverage=cover)
    (fee,) = ServiceLine.objects.filter(visit=visit)
    assert orders.line_state(fee) == "requested"

    # 2. Consultation fee in cash.
    shift1 = pay.open_shift(cashier, D("1000.00"))
    inv1 = fin.invoice(visit, cashier)
    assert (inv1.gross_total, inv1.payer_total, inv1.patient_total) == (
        D("5000.00"),
        D("0.00"),
        D("5000.00"),
    )
    pay.record_payment(shift1, patient, "cash", D("5000.00"), actor=cashier, auto=True)
    assert _state(fee) == ("settled", "pending")

    # 3. Doctor: the paid visit is in the queue; finishing performs the fee line.
    entry = QueueEntry.objects.get(visit=visit)
    entry = visits.start_consultation(entry, actor=doctor.user)
    visits.finish_consultation(entry, actor=doctor.user)
    assert _state(fee) == ("settled", "performed")
    lab, inj, dress, drug = fin.order(
        visit, doctor.user, cbc, injection, dressing, (paracetamol, 10)
    )
    assert {orders.line_state(x) for x in (lab, inj, dress, drug)} == {"requested"}
    # Nothing unpaid reaches a work list (invariant 1).
    assert not orders.worklist(["lab", "procedure", "drug"]).exists()

    # 4. Invoice: the lab line is split 7000 payer / 3000 patient.
    inv2 = fin.invoice(visit, cashier)
    lab_line = inv2.lines.get(service_line=lab)
    assert (lab_line.gross, lab_line.payer_share, lab_line.patient_share) == (
        D("10000.00"),
        D("7000.00"),
        D("3000.00"),
    )
    assert inv2.patient_total == D("7000.00")  # 3000 + 2000 + 1500 + 500
    assert inv2.payer_total == D("7000.00")
    transfer = pay.record_payment(
        shift1,
        patient,
        "bank_transfer",
        D("3000.00"),
        actor=cashier,
        bank=fin.Bank.objects.get(code="BOK"),
        reference="FT 2610-0001",
        allocations=[(inv2, D("3000.00"))],
    )
    assert transfer.verification == "pending"
    pay.record_payment(shift1, patient, "cash", D("4000.00"), actor=cashier, auto=True)
    for line in (lab, inj, dress, drug):
        assert _state(line) == ("settled", "pending")
    fin.assert_books_balance()
    fin.assert_positions_match_ledger(patient)

    # 5. Departments perform paid lines.
    assert set(orders.worklist("lab").values_list("id", flat=True)) == {lab.pk}
    orders.start_line(lab, lab_tech)
    orders.perform_line(lab, lab_tech)
    orders.perform_line(inj, nurse)
    orders.perform_line(drug, pharmacist)

    # 6. Shift close, 100 short. Pending money is not confirmed collection.
    summary = pay.shift_summary(shift1)
    assert summary.collection.cash_confirmed == D("9000.00")
    assert summary.collection.bank_pending == D("3000.00")
    assert summary.collection.confirmed_collection == D("9000.00")
    # The ledger's drawer is the expected cash, float included (ADR 0006).
    assert ledger.account_balance("CASH", shift=shift1) == pay.expected_cash(shift1)
    shift1 = pay.close_shift(
        shift1, D("9900.00"), actor=cashier, reason="COUNTING_ERROR", note="recount"
    )
    assert (shift1.expected_cash, shift1.variance) == (D("10000.00"), D("-100.00"))
    assert ledger.account_balance("CASH_OVER_SHORT", shift=shift1) == D("100.00")
    # The counted cash left the drawer for the safe: the closed shift's cash is zero.
    assert ledger.account_balance("CASH", shift=shift1) == D("0.00")
    assert ledger.account_balance("CASH_SAFE") == D("9900.00") - shift1.opening_float
    assert Notification.objects.filter(user=manager, kind="shift_variance").exists()
    report_at_close = pay.shift_summary(shift1)

    # 7. Next day: the transfer never arrived. The supervisor rejects it from their own
    # open shift; the closed shift is untouched and the reversal is linked to the original.
    shift2 = pay.open_shift(cashier2, D("1000.00"))
    sup_shift = pay.open_shift(supervisor, D("0.00"))
    rejection = pay.reject_transfer(transfer, actor=supervisor, reason="NOT_RECEIVED")
    assert rejection.reversal is not None
    assert rejection.reversal.shift == sup_shift
    assert rejection.reversal.amount == D("-3000.00")
    assert rejection.reversal.reversal_of == transfer
    assert fin.refreshed(shift1).status == "closed"
    # The closed shift's report is the one taken at close (invariant 3); the rejection is
    # reported in the supervisor's acting shift.
    assert pay.shift_summary(shift1) == report_at_close
    assert pay.shift_summary(sup_shift).late_reversals == D("3000.00")
    # 4000 cash now covers lines in order: lab 3000, injection 1000 of 2000.
    assert _state(lab) == ("settled", "performed")
    assert _state(inj) == ("invoiced", "performed")
    assert _state(dress) == ("invoiced", "pending")
    assert _state(drug) == ("invoiced", "performed")
    assert not orders.worklist("procedure").filter(pk=dress.pk).exists()
    assert billing.invoice_position(inv2).outstanding == D("3000.00")
    assert Notification.objects.filter(user=manager, kind="transfer_rejected").exists()
    entries = JournalEntry.objects.filter(source_type="transfer_reject", source_id=transfer.pk)
    assert [e.shift_id for e in entries] == [sup_shift.pk]
    fin.assert_books_balance()
    fin.assert_positions_match_ledger(patient)

    # 8. The patient pays again in cash.
    pay.record_payment(shift2, patient, "cash", D("3000.00"), actor=cashier2, auto=True)
    for line in (inj, dress, drug):
        assert _state(line)[0] == "settled"

    # 9. Dressing cannot be done: cancelled with a reason. A credit note credits it, the
    # money becomes patient credit and a refund request opens automatically.
    orders.cancel_line(dress, "EQUIPMENT_DOWN", supervisor)
    assert _state(dress) == ("credited", "cancelled")
    refund = Refund.objects.get(patient=patient)
    assert refund.amount == D("1500.00")
    assert refund.status == "requested"
    assert pay.credit_balance(patient) == D("1500.00")
    assert pay.patient_balance(patient).spendable == D("1500.00")

    # 10. Another supervisor (the accountant) approves the supervisor's request; the cashier
    # pays it from the current shift.
    accountant = fin.staff("accountant")
    pay.approve_refund(refund, actor=accountant)
    refund = pay.pay_refund(refund, actor=cashier2)
    assert refund.shift == shift2
    assert pay.credit_balance(patient) == D("0.00")
    assert pay.expected_cash(shift2) == D("2500.00")  # 1000 + 3000 - 1500

    # The books: balanced, documents equal ledger, payer share is a receivable only.
    fin.assert_books_balance()
    fin.assert_positions_match_ledger(patient)
    assert ledger.account_balance("AR_PATIENT", patient=patient) == D("0.00")
    assert ledger.account_balance("AR_PAYER", payer=insurer) == D("7000.00")
    assert ledger.account_balance("BANK_PENDING") == D("0.00")
    assert ledger.account_balance("BANK") == D("0.00")
    assert ledger.account_balance("REVENUE") == D("17500.00")  # 5000+10000+2000+500
    assert ledger.account_balance("PATIENT_CREDIT", patient=patient) == D("0.00")
    assert ledger.account_balance("CASH", shift=shift2) == D("2500.00") == pay.expected_cash(shift2)
    balance = pay.patient_balance(patient)
    assert (balance.credit, balance.outstanding) == (D("0.00"), D("0.00"))
    assert Payment.objects.filter(patient=patient, reversal_of__isnull=False).count() == 1
