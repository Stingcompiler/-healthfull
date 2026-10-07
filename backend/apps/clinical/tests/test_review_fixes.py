"""Regression tests for the Phase 1 review: the center's estimated-cost switch (FEATURES 3.8)
and clinical data following a merged file (FEATURES 1.4)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from api.errors import PermissionRequired
from apps.catalog.models import CoverageRule
from apps.catalog.tests import engine
from apps.clinical import services as cs
from apps.clinical.models import Allergy
from apps.core.models import Policy
from apps.core.tests import builders as b
from apps.patients import services as patients
from domain.errors import DomainError

pytestmark = pytest.mark.django_db
D = Decimal


def test_estimated_cost_needs_the_center_switch_and_the_permission(make_user) -> None:
    doctor = make_user(roles=["doctor"])
    allowed = make_user(roles=["admin"])
    svc = b.service("lab")
    engine.price_version().items.create(service=svc, unit_price=D("200.00"))
    payer = b.payer()
    CoverageRule.objects.create(payer=payer, rule_kind="percentage", payer_percent=D(75))
    visit = b.visit(payer=payer)
    with pytest.raises(DomainError) as exc:
        cs.estimated_cost(visit, [(svc, 2)], actor=allowed)
    assert exc.value.code == "ESTIMATED_COST_DISABLED"
    Policy.objects.update(show_estimated_cost=True)
    with pytest.raises(PermissionRequired):
        cs.estimated_cost(visit, [(svc, 2)], actor=doctor)
    (row,) = cs.estimated_cost(visit, [(svc, 2)], actor=allowed)
    assert (row.service_id, row.quantity, row.patient_share) == (svc.pk, 2, D("100.00"))


def test_merge_moves_clinical_safety_data_through_the_clinical_service(make_user) -> None:
    admin = make_user(roles=["admin"])
    dup, survivor = b.patient(), b.patient()
    Allergy.objects.create(
        patient=dup, allergen_type="other", substance="Penicillin", recorded_by=admin
    )
    patients.merge_patients(dup, survivor, actor=admin, reason_note="same person")
    assert Allergy.objects.get(substance="Penicillin").patient == survivor


def test_policy_keeps_pay_first_on() -> None:
    b.db_rejects(
        lambda: Policy.objects.update(default_pay_first=False), "core_policy_pay_first_always"
    )
