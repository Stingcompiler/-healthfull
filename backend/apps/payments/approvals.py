"""Desk approvals: a supervisor approves at the cashier's desk with their own credentials.

Some cashier actions need a second person on the spot (FEATURES 5.9, 6.2): a discount above
the cashier's limit, or a transfer reference already used for the bank. The money still goes
into the cashier's own shift, so the supervisor does not take over the screen: they type
their username and password into the cashier's dialog and the service records them as the
approver (invariant 4). ADR 0009.

The check is the one credential door of ADR 0005 (``authenticate_credentials``): lockout,
per-address throttle and audit apply exactly as at login. A wrong password answers
``APPROVER_INVALID`` (409), never 401, which would end the cashier's own session.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.http import HttpRequest

from apps.core.models import User
from apps.core.services import authenticate_credentials, holds_permission
from domain.errors import DomainError

__all__ = ["ApproverLogin", "approver_holding", "resolve_approver", "resolve_second_approver"]


@dataclass(frozen=True, slots=True)
class ApproverLogin:
    """Credentials a supervisor typed into the cashier's approval dialog."""

    request: HttpRequest
    username: str
    password: str


def _invalid() -> DomainError:
    return DomainError("APPROVER_INVALID", "The approver's username or password is wrong")


def resolve_approver(login: ApproverLogin | None, *, actor: User) -> User | None:
    """The supervisor behind ``login``, or None when there is no separate approver.

    None for no credentials, or for the actor's own credentials (the actor's own
    permissions and limits then apply). The caller's rule checks what the approver may
    approve (``payments.override_duplicate``, the role's discount limit).

    Raises:
        DomainError: ``APPROVER_INVALID`` (wrong or unknown credentials, inactive account,
            pending password change), ``ACCOUNT_LOCKED`` (423), ``RATE_LIMITED`` (429).
    """
    if login is None:
        return None
    result = authenticate_credentials(login.request, login.username.strip(), login.password)
    if isinstance(result, DomainError):
        if result.code == "INVALID_CREDENTIALS":
            raise _invalid()
        raise result
    if result.must_change_password or not result.is_active:
        raise _invalid()
    if result.pk == actor.pk:
        return None
    return result


def approver_holding(approver: User, permission: str) -> User:
    """``approver`` when they hold ``permission``.

    Raises:
        DomainError: ``APPROVER_NOT_PERMITTED`` (409, with ``permission``), never a 403
            that would read as the actor's own lack of permission.
    """
    if not holds_permission(approver, permission):
        raise DomainError(
            "APPROVER_NOT_PERMITTED",
            "The approver may not approve this action",
            permission=permission,
        )
    return approver


def resolve_second_approver(login: ApproverLogin | None, *, actor: User, permission: str) -> User:
    """The second person who approves at the actor's desk (ADR 0018).

    Unlike :func:`resolve_approver`, an approver is required and must be someone else:
    no credentials, or the actor's own, answer ``SECOND_APPROVER_REQUIRED``.

    Raises:
        DomainError: ``SECOND_APPROVER_REQUIRED``, ``APPROVER_NOT_PERMITTED``, and the
            errors of :func:`resolve_approver`.
    """
    approver = resolve_approver(login, actor=actor)
    if approver is None:
        raise DomainError("SECOND_APPROVER_REQUIRED", "Another person must approve this action")
    return approver_holding(approver, permission)
