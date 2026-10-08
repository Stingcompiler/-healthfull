"""Desk approvals: a supervisor approves at the cashier's desk by entering their credentials.

The credential check is the one door of ADR 0005 (lockout, throttle, audit). A wrong password
must never answer 401: that status ends the cashier's own session in the SPA.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import RequestFactory

from apps.core.models import AuthEvent, AuthEventKind, User
from apps.payments.approvals import ApproverLogin, resolve_approver
from conftest import TEST_PASSWORD
from domain.errors import DomainError

pytestmark = pytest.mark.django_db


def _login(username: str, password: str = TEST_PASSWORD) -> ApproverLogin:
    request = RequestFactory().post("/api/payments/payments")
    return ApproverLogin(request=request, username=username, password=password)


def test_no_login_means_no_separate_approver(make_user: Any) -> None:
    actor = make_user("cash1", roles=["cashier"])
    assert resolve_approver(None, actor=actor) is None


def test_right_credentials_return_the_supervisor(make_user: Any) -> None:
    actor = make_user("cash2", roles=["cashier"])
    sup = make_user("sup2", roles=["cashier_supervisor"])
    assert resolve_approver(_login("sup2"), actor=actor) == sup
    assert AuthEvent.objects.filter(user=sup, kind=AuthEventKind.LOGIN_FAILED).count() == 0


def test_wrong_password_is_a_conflict_and_counts_toward_lockout(make_user: Any) -> None:
    actor = make_user("cash3", roles=["cashier"])
    sup = make_user("sup3", roles=["cashier_supervisor"])
    with pytest.raises(DomainError) as exc:
        resolve_approver(_login("sup3", "wrong-password"), actor=actor)
    assert exc.value.code == "APPROVER_INVALID"
    sup.refresh_from_db()
    assert AuthEvent.objects.filter(user=sup, kind=AuthEventKind.LOGIN_FAILED).count() == 1


def test_unknown_username_answers_like_a_wrong_password(make_user: Any) -> None:
    actor = make_user("cash4", roles=["cashier"])
    with pytest.raises(DomainError) as exc:
        resolve_approver(_login("nobody-here"), actor=actor)
    assert exc.value.code == "APPROVER_INVALID"


def test_a_pending_password_change_cannot_approve(make_user: Any) -> None:
    actor = make_user("cash5", roles=["cashier"])
    make_user("sup5", roles=["cashier_supervisor"], must_change_password=True)
    with pytest.raises(DomainError) as exc:
        resolve_approver(_login("sup5"), actor=actor)
    assert exc.value.code == "APPROVER_INVALID"


def test_the_actor_approving_themselves_is_no_separate_approver(make_user: Any) -> None:
    actor: User = make_user("sup6", roles=["cashier_supervisor"])
    assert resolve_approver(_login("sup6"), actor=actor) is None


def test_a_locked_account_stays_locked(make_user: Any) -> None:
    actor = make_user("cash7", roles=["cashier"])
    make_user("sup7", roles=["cashier_supervisor"])
    for _ in range(5):
        with pytest.raises(DomainError):
            resolve_approver(_login("sup7", "bad"), actor=actor)
    with pytest.raises(DomainError) as exc:
        resolve_approver(_login("sup7"), actor=actor)
    assert exc.value.code == "ACCOUNT_LOCKED"
