"""Lab services: work list, samples, flagged results, approval, amendments, cannot-perform."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.catalog.tests import engine
from apps.core.tests import builders as b
from apps.lab import services as ls
from apps.lab.models import (
    LabParameter,
    LabTest,
    ReferenceRange,
    ResultSet,
    ResultValue,
    ResultVersion,
    Sample,
)
from apps.orders.models import PerformAuthorization, ServiceLine
from domain.errors import DomainError

pytestmark = pytest.mark.django_db


def lab_line(visit, test: LabTest, **extra) -> ServiceLine:
    """A lab line: settled (default) or invoiced through an approved invoice, or unbilled."""
    status = extra.pop("billing_status", "settled")
    if status == "unbilled":
        return b.service_line(visit, test.service, **extra)
    return b.billed_line(visit, test.service, billing_status=status, **extra)


def adult(sex: str = "male"):
    return b.patient(sex=sex, date_of_birth=date(1980, 1, 1))


def received(visit, lines, tech):
    sample = ls.collect_sample(visit=visit, lines=lines, actor=tech)
    return ls.receive_sample(sample, actor=tech)


def _approve_directly(line: ServiceLine, supervisor) -> ResultVersion:
    """Approve the first draft without the financial engine (setup for amendment tests)."""
    now = timezone.now()
    version = ResultVersion.objects.get(result_set__service_line=line, status="draft")
    ResultVersion.objects.filter(pk=version.pk).update(
        status="approved", approved_by=supervisor, approved_at=now
    )
    ResultSet.objects.filter(service_line=line).update(first_approved_at=now)
    ServiceLine.objects.filter(pk=line.pk).update(
        fulfilment_status="performed", performed_at=now, performed_by=supervisor
    )
    version.refresh_from_db()
    return version


# --- work list and samples ------------------------------------------------------------------


def test_worklist_shows_paid_or_authorized_lab_lines(tech, cbc) -> None:
    visit = b.visit(adult())
    paid = lab_line(visit, cbc)
    lab_line(visit, cbc, billing_status="unbilled")
    auth = PerformAuthorization.objects.create(
        visit=visit,
        kind="emergency",
        reason_code=b.reason("perform_first"),
        authorized_by=tech,
        authorized_at=timezone.now(),
    )
    authorized = lab_line(visit, cbc, billing_status="unbilled", authorization=auth)
    b.billed_line(visit, b.service("drug"))
    assert [ln.pk for ln in ls.worklist(visit=visit)] == [paid.pk, authorized.pk]


def test_collect_and_receive_sample(tech, cbc, malaria) -> None:
    visit = b.visit(adult())
    a, c = lab_line(visit, cbc), lab_line(visit, malaria)
    sample = ls.collect_sample(visit=visit, lines=[a, c], actor=tech)
    assert sample.accession_no.startswith("LAB-")
    assert sample.sample_type == "whole_blood"
    assert ResultSet.objects.filter(sample=sample).count() == 2
    with pytest.raises(DomainError) as exc:
        ls.collect_sample(visit=visit, lines=[a], actor=tech)
    assert exc.value.code == "SAMPLE_ALREADY_COLLECTED"
    got = ls.receive_sample(sample, actor=tech)
    assert got.status == "received"
    assert got.received_by == tech
    with pytest.raises(DomainError) as exc:
        ls.receive_sample(sample, actor=tech)
    assert exc.value.code == "SAMPLE_NOT_COLLECTED"


def test_collect_sample_refusals(tech, cbc) -> None:
    visit = b.visit(adult())
    urine = LabTest.objects.create(service=b.service("lab"), code="UA", sample_type="urine")
    unpaid = lab_line(visit, cbc, billing_status="unbilled")
    drug = b.billed_line(visit, b.service("drug"))
    no_test = b.billed_line(visit, b.service("lab"))  # a lab service without a lab test
    cases = [
        ([], "SAMPLE_EMPTY"),
        ([unpaid], "LINE_NOT_ELIGIBLE"),
        ([drug], "LINE_NOT_LAB"),
        ([no_test], "LAB_TEST_UNKNOWN"),
        ([lab_line(visit, cbc), lab_line(visit, urine)], "SAMPLE_TYPE_MISMATCH"),
        ([lab_line(b.visit(), cbc)], "LINE_NOT_ON_VISIT"),
    ]
    for lines, code in cases:
        with pytest.raises(DomainError) as exc:
            ls.collect_sample(visit=visit, lines=lines, actor=tech)
        assert exc.value.code == code
    assert not Sample.objects.exists()


def test_rejected_sample_needs_a_new_one(tech, cbc) -> None:
    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    sample = ls.collect_sample(visit=visit, lines=[line], actor=tech)
    with pytest.raises(DomainError) as exc:
        ls.reject_sample(sample, actor=tech, reason_code="OTHER")
    assert exc.value.code == "REASON_NOTE_REQUIRED"
    rejected = ls.reject_sample(sample, actor=tech, reason_code="HEMOLYZED")
    assert rejected.status == "rejected"
    assert rejected.rejection_reason is not None
    with pytest.raises(DomainError) as exc:
        ls.enter_results(line, values={"HB": "14"}, actor=tech)
    assert exc.value.code == "SAMPLE_NOT_RECEIVED"
    second = ls.collect_sample(visit=visit, lines=[line], actor=tech)
    assert ResultSet.objects.get(service_line=line).sample == second


# --- result entry and flags -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("sex", "dob", "value", "flag", "low", "high"),
    [
        ("male", date(1980, 1, 1), "12.0", "low", Decimal(13), Decimal(17)),
        ("male", date(1980, 1, 1), "6.9", "critical_low", Decimal(13), Decimal(17)),
        ("male", date(1980, 1, 1), "20", "critical_high", Decimal(13), Decimal(17)),
        ("female", date(1980, 1, 1), "12.0", "normal", Decimal(12), Decimal("15.5")),
        ("female", date(1980, 1, 1), "16", "high", Decimal(12), Decimal("15.5")),
        (
            "male",
            timezone.localdate() - timedelta(days=6 * 365),
            "11.5",
            "normal",
            Decimal(11),
            Decimal("14.5"),
        ),
        ("female", None, "12.0", "none", None, None),
    ],
)
def test_values_are_flagged_by_sex_and_age(tech, cbc, sex, dob, value, flag, low, high) -> None:
    visit = b.visit(b.patient(sex=sex, date_of_birth=dob))
    line = lab_line(visit, cbc)
    received(visit, [line], tech)
    version = ls.enter_results(line, values={"HB": value, "BG": "O"}, actor=tech)
    hb = ResultValue.objects.get(version=version, parameter__code="HB")
    assert hb.flag == flag
    assert (hb.reference_low, hb.reference_high) == (low, high)
    assert hb.unit == "g/dL"
    bg = ResultValue.objects.get(version=version, parameter__code="BG")
    assert (bg.value_text, bg.flag) == ("O", "none")


def test_result_entry_validation_and_correction(tech, cbc, malaria) -> None:
    visit = b.visit(adult())
    line, mal = lab_line(visit, cbc), lab_line(visit, malaria)
    with pytest.raises(DomainError) as exc:
        ls.enter_results(line, values={"HB": "1"}, actor=tech)
    assert exc.value.code == "SAMPLE_NOT_COLLECTED"
    sample = ls.collect_sample(visit=visit, lines=[line, mal], actor=tech)
    with pytest.raises(DomainError) as exc:
        ls.enter_results(line, values={"HB": "1"}, actor=tech)
    assert exc.value.code == "SAMPLE_NOT_RECEIVED"
    ls.receive_sample(sample, actor=tech)
    cases = [
        ({"HB": "abc"}, "RESULT_VALUE_INVALID"),
        ({"HB": "NaN"}, "RESULT_VALUE_INVALID"),
        ({"BG": "Z"}, "RESULT_VALUE_INVALID"),
        ({"XX": "1"}, "PARAMETER_UNKNOWN"),
    ]
    for values, code in cases:
        with pytest.raises(DomainError) as exc:
            ls.enter_results(line, values=values, actor=tech)
        assert exc.value.code == code
    v1 = ls.enter_results(line, values={"HB": "13.46"}, actor=tech, comment="first")
    assert ResultValue.objects.get(version=v1).value_numeric == Decimal("13.5")  # 1 decimal
    v1b = ls.enter_results(line, values={"HB": "14.2"}, actor=tech)
    assert v1b.pk == v1.pk  # still the same draft
    assert ResultValue.objects.get(version=v1).value_numeric == Decimal("14.2")
    positive = ls.enter_results(mal, values={"MP": "Positive"}, actor=tech)
    mp = ResultValue.objects.get(version=positive)
    assert (mp.value_text, mp.flag, mp.reference_text) == ("positive", "abnormal", "negative")
    with pytest.raises(DomainError) as exc:
        ls.enter_results(mal, values={"MP": "maybe"}, actor=tech)
    assert exc.value.code == "RESULT_VALUE_INVALID"


def test_unpaid_line_cannot_get_results(tech, cbc) -> None:
    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    received(visit, [line], tech)
    ServiceLine.objects.filter(pk=line.pk).update(billing_status="invoiced")
    with pytest.raises(DomainError) as exc:
        ls.enter_results(line, values={"HB": "14"}, actor=tech)
    assert exc.value.code == "LINE_NOT_ELIGIBLE"


def test_misconfigured_range_is_reported(tech, cbc) -> None:
    hb = LabParameter.objects.get(test=cbc, code="HB")
    ReferenceRange.objects.filter(parameter=hb).delete()
    ReferenceRange.objects.create(
        parameter=hb, low=Decimal(13), high=Decimal(17), critical_low=Decimal(13)
    )
    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    received(visit, [line], tech)
    with pytest.raises(DomainError) as exc:
        ls.enter_results(line, values={"HB": "14"}, actor=tech)
    assert exc.value.code == "INVALID_REFERENCE_RANGE"
    assert exc.value.details["parameter_id"] == hb.pk


# --- approval -------------------------------------------------------------------------------


def test_approval_needs_supervisor_and_complete_results(tech, supervisor, cbc) -> None:
    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    received(visit, [line], tech)
    with pytest.raises(DomainError) as exc:
        ls.approve_results(line, actor=supervisor)
    assert exc.value.code == "RESULT_NOT_DRAFT"
    ls.enter_results(line, values={"HB": "14"}, actor=tech)
    with pytest.raises(PermissionDenied):
        ls.approve_results(line, actor=tech)
    with pytest.raises(DomainError) as exc:
        ls.approve_results(line, actor=supervisor)
    assert exc.value.code == "RESULT_INCOMPLETE"
    assert ls.visible_result(line) is None  # drafts are never visible


def test_first_approval_performs_the_line(tech, supervisor, cbc) -> None:
    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    received(visit, [line], tech)
    ls.enter_results(line, values={"HB": "6.5", "BG": "A"}, actor=tech)
    version = ls.approve_results(line, actor=supervisor)
    assert version.status == "approved"
    assert version.approved_by == supervisor
    line.refresh_from_db()
    assert line.fulfilment_status == "performed"
    assert ls.visible_result(line) == version
    assert [v.parameter.code for v in ls.critical_flags(version)] == ["HB"]
    rs = ResultSet.objects.get(service_line=line)
    assert rs.first_approved_at is not None
    assert ls.turnaround_minutes(rs) == 0


def test_amendment_keeps_the_original(tech, supervisor, cbc) -> None:
    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    received(visit, [line], tech)
    ls.enter_results(line, values={"HB": "14", "BG": "A"}, actor=tech)
    v1 = _approve_directly(line, supervisor)
    with pytest.raises(DomainError) as exc:
        ls.enter_results(line, values={"HB": "15"}, actor=tech)
    assert exc.value.code == "RESULT_APPROVED_IMMUTABLE"
    with pytest.raises(PermissionDenied):
        ls.start_amendment(line, actor=tech, reason_code="ENTRY_ERROR")
    with pytest.raises(DomainError) as exc:
        ls.start_amendment(line, actor=supervisor, reason_code="OTHER")
    assert exc.value.code == "REASON_NOTE_REQUIRED"
    v2 = ls.start_amendment(line, actor=supervisor, reason_code="ENTRY_ERROR", note="typo")
    assert (v2.version_no, v2.amends, v2.status) == (2, v1, "draft")
    assert ResultValue.objects.filter(version=v2).count() == 2  # values copied
    with pytest.raises(DomainError) as exc:
        ls.start_amendment(line, actor=supervisor, reason_code="ENTRY_ERROR")
    assert exc.value.code == "AMENDMENT_IN_PROGRESS"
    assert ls.visible_result(line) == v1  # the original stays visible until approval
    ls.enter_results(line, values={"BG": "B"}, actor=supervisor)
    approved = ls.approve_results(line, actor=supervisor)  # not the first: no line change
    assert approved.pk == v2.pk
    v1.refresh_from_db()
    assert v1.status == "amended"
    assert v1.superseded_by == supervisor
    assert ls.visible_result(line) == approved
    assert ResultValue.objects.get(version=v1, parameter__code="BG").value_text == "A"
    assert ResultValue.objects.get(version=v2, parameter__code="BG").value_text == "B"
    # The superseded version is frozen by the database.
    b.db_rejects(
        lambda: ResultVersion.objects.filter(pk=v1.pk).update(comment="edited"),
        "RESULT_FROZEN",
    )


# --- cannot perform -------------------------------------------------------------------------


def test_cannot_perform_refuses_approved_results(tech, supervisor, cbc) -> None:
    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    received(visit, [line], tech)
    ls.enter_results(line, values={"HB": "14", "BG": "A"}, actor=tech)
    _approve_directly(line, supervisor)
    with pytest.raises(DomainError) as exc:
        ls.cannot_perform(line, actor=supervisor, reason_code="EQUIPMENT_DOWN")
    assert exc.value.code == "RESULT_APPROVED_IMMUTABLE"
    with pytest.raises(DomainError) as exc:
        ls.cannot_perform(line, actor=supervisor, reason_code="NOPE")
    assert exc.value.code == "REASON_UNKNOWN"


def test_cannot_perform_credits_and_cancels_the_line(make_user, tech, cbc) -> None:
    from apps.billing.models import CreditNoteLine

    line = engine.settled_line(cbc.service, 1, tech)
    # The credit note is approved by a billing supervisor, never by the lab (FEATURES 5.11).
    with pytest.raises(DomainError) as exc:
        ls.cannot_perform(line, actor=tech, reason_code="EQUIPMENT_DOWN")
    assert exc.value.code == "CANCEL_NEEDS_BILLING_APPROVER"
    approver = make_user(roles=["cashier_supervisor"])
    ls.cannot_perform(line, actor=tech, reason_code="EQUIPMENT_DOWN", approver=approver)
    line.refresh_from_db()
    assert line.fulfilment_status == "cancelled"
    assert line.billing_status == "credited"
    assert line.cancel_reason is not None
    assert line.cancel_reason.code == "EQUIPMENT_DOWN"
    assert CreditNoteLine.objects.get(invoice_line__service_line=line).credit_note.status == (
        "approved"
    )
    assert not ls.worklist(visit=line.visit).exists()


def test_unbilled_authorized_test_that_cannot_be_done_is_cancelled(tech, cbc) -> None:
    visit = b.visit(adult())
    auth = PerformAuthorization.objects.create(
        visit=visit,
        kind="emergency",
        reason_code=b.reason("perform_first"),
        authorized_by=tech,
        authorized_at=timezone.now(),
    )
    line = lab_line(visit, cbc, billing_status="unbilled", authorization=auth)
    ls.cannot_perform(line, actor=tech, reason_code="SAMPLE_UNUSABLE")
    line.refresh_from_db()
    assert (line.fulfilment_status, line.billing_status) == ("cancelled", "unbilled")


def test_cannot_perform_after_cash_payment_opens_a_refund(make_user, tech, cbc) -> None:
    from apps.payments import services as payments
    from apps.payments.models import Refund

    cashier = make_user(roles=["cashier"])
    line = engine.cash_paid_line(cbc.service, 1, cashier, unit_price="150.00")
    patient = line.visit.patient
    approver = make_user(roles=["cashier_supervisor"])
    ls.cannot_perform(line, actor=tech, reason_code="EQUIPMENT_DOWN", approver=approver)
    refund = Refund.objects.get(patient=patient)
    assert refund.requested_by == tech  # someone other than the requester approves it
    assert refund.amount == Decimal("150.00")
    assert refund.status == "requested"
    assert payments.credit_balance(patient) == Decimal("150.00")


def test_approval_notifies_the_ordering_doctor(make_user, tech, supervisor, cbc) -> None:
    from apps.core.models import Notification

    doctor = b.doctor()
    visit = b.visit(adult(), doctor=doctor, department=doctor.department)
    orderer = make_user(roles=["doctor"])
    line = b.billed_line(visit, cbc.service, ordered_by=orderer)
    received(visit, [line], tech)
    ls.enter_results(line, values={"HB": "6.0", "BG": "O"}, actor=tech)
    ls.approve_results(line, actor=supervisor)
    notes = Notification.objects.filter(kind="lab_result_critical")
    assert set(notes.values_list("user_id", flat=True)) == {orderer.pk, doctor.user_id}
    assert notes.values_list("payload", flat=True)[0]["critical"] == ["HB"]


def test_label_and_catalog_helpers(tech, supervisor) -> None:
    with pytest.raises(DomainError) as exc:
        ls.create_lab_test(
            service=b.service("drug"), code="X", sample_type="serum", actor=supervisor
        )
    assert exc.value.code == "SERVICE_NOT_LAB"
    with pytest.raises(DomainError) as exc:
        ls.create_lab_test(
            service=b.service("lab"), code="X", sample_type="blood", actor=supervisor
        )
    assert exc.value.code == "INVALID_SAMPLE_TYPE"
    test = ls.create_lab_test(
        service=b.service("lab"),
        code="GLU",
        sample_type="serum",
        actor=supervisor,
        method="GOD-PAP",
    )
    with pytest.raises(DomainError) as exc:
        ls.create_lab_test(
            service=b.service("lab"), code="GLU", sample_type="serum", actor=supervisor
        )
    assert exc.value.code == "LAB_TEST_EXISTS"
    param = LabParameter.objects.create(test=test, code="GLU", name_ar="سكر", name_en="Glucose")
    rng = ls.add_reference_range(
        param, actor=supervisor, low=Decimal(70), high=Decimal(110), critical_low=Decimal(40)
    )
    assert rng.pk
    with pytest.raises(DomainError) as exc:
        ls.add_reference_range(param, actor=supervisor, low=Decimal(70), critical_low=Decimal(70))
    assert exc.value.code == "INVALID_REFERENCE_RANGE"
    with pytest.raises(DomainError) as exc:
        ls.add_reference_range(param, actor=supervisor, age_min_days=10, age_max_days=5)
    assert exc.value.code == "INVALID_REFERENCE_RANGE"
    visit = b.visit(adult())
    sample = ls.collect_sample(visit=visit, lines=[lab_line(visit, test)], actor=tech)
    assert ls.mark_label_printed(sample, actor=tech).label_printed_at is not None


def test_turnaround_minutes(tech, cbc) -> None:
    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    sample = received(visit, [line], tech)
    rs = ResultSet.objects.get(service_line=line)
    assert ls.turnaround_minutes(rs) is None
    rs.first_approved_at = sample.received_at + timedelta(minutes=95)
    assert ls.turnaround_minutes(rs) == 95
