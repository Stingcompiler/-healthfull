"""Core helpers used by the money and order services: reasons, permissions, notifications."""

from __future__ import annotations

import pytest

from api.errors import PermissionRequired
from apps.core import services as core
from apps.core.models import Notification, ReasonCode
from apps.payments.tests import fin
from domain.errors import DomainError

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _seed() -> None:
    fin.seed()


def test_resolve_reason_by_code_or_instance() -> None:
    found = core.resolve_reason("PATIENT_REFUSED", "line_cancel")
    assert (found.category, found.code) == ("line_cancel", "PATIENT_REFUSED")
    assert core.resolve_reason(found, "line_cancel") == found
    assert core.resolve_reason("OTHER", "line_cancel", note="why").code == "OTHER"


@pytest.mark.parametrize(
    ("reason", "category", "note", "code"),
    [
        (None, "line_cancel", "", "REASON_REQUIRED"),
        ("", "line_cancel", "", "REASON_REQUIRED"),
        ("NOPE", "line_cancel", "", "REASON_UNKNOWN"),
        ("STAFF", "line_cancel", "", "REASON_UNKNOWN"),  # a discount reason
        ("OTHER", "line_cancel", "  ", "REASON_NOTE_REQUIRED"),
    ],
)
def test_resolve_reason_refusals(reason, category, note, code) -> None:
    with pytest.raises(DomainError) as exc:
        core.resolve_reason(reason, category, note)
    assert exc.value.code == code


def test_inactive_or_foreign_reason_instance_is_refused() -> None:
    discount = ReasonCode.objects.get(category="discount", code="STAFF")
    with pytest.raises(DomainError) as exc:
        core.resolve_reason(discount, "line_cancel")
    assert exc.value.code == "REASON_UNKNOWN"
    ReasonCode.objects.filter(category="line_cancel", code="ORDER_ERROR").update(active=False)
    with pytest.raises(DomainError) as exc:
        core.resolve_reason("ORDER_ERROR", "line_cancel")
    assert exc.value.code == "REASON_UNKNOWN"


def test_permission_helpers() -> None:
    supervisor, cashier = fin.staff("cashier_supervisor"), fin.staff("cashier")
    assert core.holds_permission(supervisor, "payments.confirm_transfer")
    assert not core.holds_permission(cashier, "payments.confirm_transfer")
    core.require_permission(supervisor, "payments.confirm_transfer")
    with pytest.raises(PermissionRequired) as exc:
        core.require_permission(cashier, "payments.confirm_transfer")
    assert exc.value.permission == "payments.confirm_transfer"
    assert core.holds_permission(fin.staff(superuser=True), "ledger.manage_accounts")


def test_notifications_reach_each_active_role_holder_once() -> None:
    manager = fin.staff("manager", "cashier_supervisor")
    other = fin.staff("cashier_supervisor")
    fin.staff("manager", is_active=False)
    fin.staff("cashier")
    assert (
        core.notify_roles(["manager", "cashier_supervisor"], "transfer_rejected", amount="5.00")
        == 2
    )
    rows = Notification.objects.filter(kind="transfer_rejected")
    assert sorted(rows.values_list("user_id", flat=True)) == sorted([manager.pk, other.pk])
    assert fin.some(rows.first()).payload == {"amount": "5.00"}
    assert core.notify_users([manager, manager], "x" * 70) == 1
    assert Notification.objects.filter(user=manager, kind="x" * 60).exists()
