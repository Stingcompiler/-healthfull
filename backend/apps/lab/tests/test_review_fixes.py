"""Regression tests for the Phase 1 review: lab work in progress (FEATURES 3.7) and
perform-first revocation under started work (invariant 1)."""

from __future__ import annotations

from datetime import date

import pytest

from apps.core.tests import builders as b
from apps.lab import services as ls
from apps.lab.models import LabParameter, LabTest
from apps.orders import services as orders
from domain.errors import DomainError

pytestmark = pytest.mark.django_db


def test_sample_starts_the_work_and_blocks_revoking_the_authorization(make_user) -> None:
    """Review: a sample taken and results entered under perform-first left the line
    'pending'; the authorization could be revoked and the result could never be approved."""
    tech = make_user(roles=["lab_tech"])
    sup = make_user(roles=["lab_supervisor"])
    boss = make_user(roles=["cashier_supervisor"])
    doctor = make_user(roles=["doctor"])
    test = LabTest.objects.create(service=b.service("lab"), code="BFX", sample_type="whole_blood")
    LabParameter.objects.create(
        test=test, code="MP", name_ar="م", name_en="MP", value_type="pos_neg"
    )
    visit = b.visit(b.patient(sex="male", date_of_birth=date(1980, 1, 1)))
    (line,) = orders.create_service_lines(visit, [{"service": test.service}], doctor)
    auth = orders.authorize_perform_first(
        [line], actor=boss, reason="OTHER", note="emergency", kind="emergency"
    )
    line.refresh_from_db()
    assert orders.doctor_status(line) == "paid"
    sample = ls.collect_sample(visit=visit, lines=[line], actor=tech)
    line.refresh_from_db()
    assert line.fulfilment_status == "in_progress"
    assert orders.doctor_status(line) == "in_progress"
    ls.receive_sample(sample, actor=tech)
    ls.enter_results(line, values={"MP": "positive"}, actor=tech)
    with pytest.raises(DomainError) as exc:
        orders.revoke_authorization(auth, actor=boss, note="changed mind")
    assert exc.value.code == "AUTHORIZATION_IN_USE"
    ls.approve_results(line, actor=sup)
    line.refresh_from_db()
    assert line.fulfilment_status == "performed"
    assert orders.doctor_status(line) == "done"
