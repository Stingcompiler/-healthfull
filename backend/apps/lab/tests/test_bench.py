"""Lab bench services added with the lab screens (FEATURES 9.1-9.8).

Catalog editing, collect-and-receive in one step, the bench stage of a line, the approval
guard against values changed after the supervisor read them, approval of a line that is
cancelled or no longer paid (invariant 1), the cannot-perform approver check and the
turnaround report.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.catalog.tests import engine
from apps.core.tests import builders as b
from apps.lab import services as ls
from apps.lab.models import LabParameter, ReferenceRange, ResultSet, ResultVersion
from apps.lab.tests.test_services import adult, lab_line, received
from apps.orders.models import ServiceLine
from domain.errors import DomainError
from domain.lab import Stage

pytestmark = pytest.mark.django_db


def _code(exc: pytest.ExceptionInfo[DomainError]) -> str:
    return exc.value.code


# --- catalog ---------------------------------------------------------------------------------


def test_update_lab_test_changes_only_allowed_fields(supervisor, cbc) -> None:
    ls.update_lab_test(cbc, actor=supervisor, turnaround_minutes=45, container="EDTA")
    cbc.refresh_from_db()
    assert (cbc.turnaround_minutes, cbc.container) == (45, "EDTA")
    with pytest.raises(DomainError) as exc:
        ls.update_lab_test(cbc, actor=supervisor, sample_type="blood")
    assert _code(exc) == "INVALID_SAMPLE_TYPE"
    with pytest.raises(DomainError) as exc:
        ls.update_lab_test(cbc, actor=supervisor, turnaround_minutes=0)
    assert _code(exc) == "INVALID_TURNAROUND"
    with pytest.raises(TypeError):
        ls.update_lab_test(cbc, actor=supervisor, code="NEW")


def test_parameters_are_validated(supervisor, cbc) -> None:
    p = ls.add_parameter(
        cbc, actor=supervisor, code=" PLT ", name_ar="الصفائح", name_en="Platelets", unit="10^9/L"
    )
    assert (p.code, p.value_type, p.decimals) == ("PLT", "numeric", 1)
    with pytest.raises(DomainError) as exc:
        ls.add_parameter(cbc, actor=supervisor, code="PLT", name_ar="x", name_en="x")
    assert _code(exc) == "PARAMETER_EXISTS"
    with pytest.raises(DomainError) as exc:
        ls.add_parameter(
            cbc, actor=supervisor, code="GRP", name_ar="x", name_en="x", value_type="choice"
        )
    assert _code(exc) == "PARAMETER_CHOICES_REQUIRED"
    with pytest.raises(DomainError) as exc:
        ls.add_parameter(cbc, actor=supervisor, code="X", name_ar="x", name_en="x", value_type="?")
    assert _code(exc) == "INVALID_VALUE_TYPE"
    with pytest.raises(DomainError) as exc:
        ls.add_parameter(cbc, actor=supervisor, code="Y", name_ar="x", name_en="x", decimals=9)
    assert _code(exc) == "PARAMETER_DECIMALS_INVALID"
    ls.update_parameter(p, actor=supervisor, active=False, unit="x10^9/L")
    p.refresh_from_db()
    assert (p.active, p.unit) == (False, "x10^9/L")
    choice = ls.add_parameter(
        cbc,
        actor=supervisor,
        code="RH",
        name_ar="عامل ريسس",
        name_en="Rhesus",
        value_type="choice",
        choices=[" Positive ", "Negative", "Negative", ""],
    )
    assert choice.choices == ["Positive", "Negative"]
    with pytest.raises(DomainError) as exc:
        ls.update_parameter(choice, actor=supervisor, choices=[])
    assert _code(exc) == "PARAMETER_CHOICES_REQUIRED"


def test_reference_ranges_are_validated_on_update_and_can_be_removed(supervisor, cbc) -> None:
    hb = LabParameter.objects.get(test=cbc, code="HB")
    rng = ReferenceRange.objects.filter(parameter=hb, sex="male").get()
    ls.update_reference_range(rng, actor=supervisor, high=Decimal("17.5"))
    rng.refresh_from_db()
    assert rng.high == Decimal("17.5")
    with pytest.raises(DomainError) as exc:
        ls.update_reference_range(rng, actor=supervisor, critical_high=Decimal(10))
    assert _code(exc) == "INVALID_REFERENCE_RANGE"
    rng.refresh_from_db()
    assert rng.critical_high == Decimal(20)
    with pytest.raises(DomainError) as exc:
        ls.update_reference_range(rng, actor=supervisor, sex="other")
    assert _code(exc) == "INVALID_REFERENCE_RANGE"
    ls.delete_reference_range(rng, actor=supervisor)
    assert not ReferenceRange.objects.filter(pk=rng.pk).exists()


# --- collect and receive, stage --------------------------------------------------------------


def test_collect_and_receive_in_one_step_starts_the_line(tech, cbc) -> None:
    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    assert ls.line_stage(line) is Stage.TO_COLLECT
    sample = ls.collect_and_receive(visit=visit, lines=[line], actor=tech)
    assert sample.status == "received"
    assert sample.received_by == tech
    line.refresh_from_db()
    assert line.fulfilment_status == "in_progress"
    assert ls.line_stage(line) is Stage.TO_ENTER
    ls.enter_results(line, values={"HB": "14"}, actor=tech)
    assert ls.line_stage(line) is Stage.TO_ENTER  # blood group still missing
    ls.enter_results(line, values={"BG": "A"}, actor=tech)
    assert ls.line_stage(line) is Stage.TO_APPROVE


def test_collected_elsewhere_waits_for_receipt(tech, cbc) -> None:
    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    sample = ls.collect_sample(visit=visit, lines=[line], actor=tech)
    assert ls.line_stage(line) is Stage.TO_RECEIVE
    ls.reject_sample(sample, actor=tech, reason_code="CLOTTED")
    assert ls.line_stage(line) is Stage.TO_COLLECT


# --- approval guards -------------------------------------------------------------------------


def test_approval_refuses_values_changed_after_they_were_read(tech, supervisor, cbc) -> None:
    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    received(visit, [line], tech)
    draft = ls.enter_results(line, values={"HB": "14", "BG": "A"}, actor=tech)
    seen = ls.result_revision(draft)
    ls.enter_results(line, values={"HB": "15"}, actor=tech)
    assert ls.result_revision(draft) != seen
    with pytest.raises(DomainError) as exc:
        ls.approve_results(line, actor=supervisor, revision=seen)
    assert _code(exc) == "RESULT_CHANGED"
    approved = ls.approve_results(line, actor=supervisor, revision=ls.result_revision(draft))
    assert approved.status == "approved"


def test_comment_change_changes_the_revision(tech, cbc) -> None:
    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    received(visit, [line], tech)
    draft = ls.enter_results(line, values={"HB": "14", "BG": "A"}, actor=tech)
    before = ls.result_revision(draft)
    ls.enter_results(line, values={}, actor=tech, comment="Repeat in 2 weeks")
    draft.refresh_from_db()
    assert ls.result_revision(draft) != before


def test_first_approval_needs_the_line_still_paid(tech, supervisor, cbc) -> None:
    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    received(visit, [line], tech)
    ls.enter_results(line, values={"HB": "14", "BG": "A"}, actor=tech)
    # A rejected transfer takes the line back to invoiced (ARCHITECTURE 4.4 rule 2).
    ServiceLine.objects.filter(pk=line.pk).update(billing_status="invoiced")
    with pytest.raises(DomainError) as exc:
        ls.approve_results(line, actor=supervisor)
    assert _code(exc) == "LINE_NOT_ELIGIBLE"
    # Nothing was approved: the draft is still a draft (invariant 1).
    assert ResultVersion.objects.get(result_set__service_line=line).status == "draft"


def test_cancelled_line_is_never_approved(make_user, tech, supervisor, cbc) -> None:
    line = engine.settled_line(cbc.service, 1, tech)
    visit = line.visit
    received(visit, [line], tech)
    ls.enter_results(line, values={"HB": "14", "BG": "A"}, actor=tech)
    approver = make_user(roles=["cashier_supervisor"])
    ls.cannot_perform(line, actor=supervisor, reason_code="EQUIPMENT_DOWN", approver=approver)
    with pytest.raises(DomainError) as exc:
        ls.approve_results(line, actor=supervisor)
    assert _code(exc) == "LINE_CANCELLED"
    assert ls.line_stage(line) is Stage.CANCELLED


def test_cannot_perform_a_paid_test_needs_a_billing_approver(make_user, supervisor, cbc) -> None:
    line = engine.settled_line(cbc.service, 1, supervisor)
    with pytest.raises(DomainError) as exc:
        ls.cannot_perform(line, actor=supervisor, reason_code="EQUIPMENT_DOWN")
    assert _code(exc) == "CANCEL_NEEDS_BILLING_APPROVER"
    nurse = make_user(roles=["nurse"])
    with pytest.raises(DomainError) as exc:
        ls.cannot_perform(line, actor=supervisor, reason_code="EQUIPMENT_DOWN", approver=nurse)
    assert _code(exc) == "CANCEL_NEEDS_BILLING_APPROVER"
    line.refresh_from_db()
    assert line.fulfilment_status == "pending"


# --- turnaround report -----------------------------------------------------------------------


def test_turnaround_report_summarises_completed_tests(tech, supervisor, cbc, malaria) -> None:
    now = timezone.now()
    minutes = []
    for i, tat in enumerate((30, 50, 90)):
        visit = b.visit(adult())
        line = lab_line(visit, cbc)
        sample = received(visit, [line], tech)
        ls.enter_results(line, values={"HB": "14", "BG": "A"}, actor=tech)
        ls.approve_results(line, actor=supervisor)
        ResultSet.objects.filter(service_line=line).update(
            first_approved_at=sample.received_at + timedelta(minutes=tat)
        )
        minutes.append(tat)
        assert i == len(minutes) - 1
    # An open test past its target counts as overdue.
    visit = b.visit(adult())
    open_line = lab_line(visit, malaria)
    sample = received(visit, [open_line], tech)
    type(sample).objects.filter(pk=sample.pk).update(received_at=now - timedelta(hours=3))

    report = ls.turnaround_report(
        date_from=timezone.localdate() - timedelta(days=1),
        date_to=timezone.localdate() + timedelta(days=1),
    )
    rows = {r.test.code: r for r in report.rows}
    assert rows["CBC"].stats.count == 3
    assert rows["CBC"].stats.median == 50
    assert rows["CBC"].stats.within_target == 2  # target 60 minutes
    assert rows["CBC"].open_overdue == 0
    assert rows["BFFM"].stats.count == 0
    assert rows["BFFM"].open_overdue == 1
    assert report.total.count == 3
    assert report.total.within_target == 2
    with pytest.raises(DomainError) as exc:
        ls.turnaround_report(
            date_from=timezone.localdate(), date_to=timezone.localdate() - timedelta(days=1)
        )
    assert _code(exc) == "INVALID_DATE_RANGE"


def test_rejecting_a_sample_discards_its_draft_values(tech, supervisor, cbc) -> None:
    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    sample = received(visit, [line], tech)
    ls.enter_results(line, values={"HB": "14", "BG": "A"}, actor=tech)
    ls.reject_sample(sample, actor=tech, reason_code="HEMOLYZED")
    # Values measured on an unusable sample never reach approval.
    assert not ResultVersion.objects.filter(result_set__service_line=line).exists()
    with pytest.raises(DomainError) as exc:
        ls.approve_results(line, actor=supervisor)
    assert _code(exc) == "RESULT_NOT_DRAFT"
    received(visit, [line], tech)
    draft = ls.enter_results(line, values={"HB": "13.5"}, actor=tech)
    assert set(draft.values.values_list("parameter__code", flat=True)) == {"HB"}


def test_only_an_amender_edits_an_amendment(tech, supervisor, cbc) -> None:
    from api.errors import PermissionRequired

    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    received(visit, [line], tech)
    ls.enter_results(line, values={"HB": "14", "BG": "A"}, actor=tech)
    ls.approve_results(line, actor=supervisor)
    ls.start_amendment(line, actor=supervisor, reason_code="ENTRY_ERROR")
    with pytest.raises(PermissionRequired):
        ls.enter_results(line, values={"HB": "15"}, actor=tech)
    draft = ls.enter_results(line, values={"HB": "15"}, actor=supervisor)
    assert draft.values.get(parameter__code="HB").value_numeric == Decimal("15.0")


def test_approval_needs_the_sample_still_received(tech, supervisor, cbc) -> None:
    visit = b.visit(adult())
    line = lab_line(visit, cbc)
    sample = received(visit, [line], tech)
    ls.enter_results(line, values={"HB": "14", "BG": "A"}, actor=tech)
    type(sample).objects.filter(pk=sample.pk).update(status="collected", received_at=None)
    with pytest.raises(DomainError) as exc:
        ls.approve_results(line, actor=supervisor)
    assert _code(exc) == "SAMPLE_NOT_RECEIVED"
