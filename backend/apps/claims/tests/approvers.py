"""The second person who approves rebills and write-offs in tests (ADR 0018).

``Policy.claims_second_approver`` is on by default, so every rebill and write-off needs an
approver other than the recording user who holds ``claims.resolve_rejection``.
"""

from __future__ import annotations

from typing import Any

from apps.core.models import Role, UserRole
from apps.core.tests import builders as b


def second() -> Any:
    """A fresh manager (holds ``claims.resolve_rejection``) to approve one resolution."""
    user = b.user()
    UserRole.objects.create(user=user, role=Role.objects.get(code="manager"))
    return user
