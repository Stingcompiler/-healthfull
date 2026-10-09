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
from apps.core.services import authenticate_credentials
from domain.errors import DomainError

__all__ = ["ApproverLogin", "resolve_approver"]


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
