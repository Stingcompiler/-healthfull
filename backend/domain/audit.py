"""Who, when and why: the record behind invariant 4.

FLOW invariant 4: every cancellation, discount, refund, transfer confirmation and override
records a reason, the approver and the time. Rules that need it take an :class:`Approval`,
which cannot be built without all three. The reason is either a code from the center's
configurable reason list (``core.ReasonCode``), free text, or both.

Error codes: ``REASON_REQUIRED``, ``APPROVER_REQUIRED``, ``INVALID_TIMESTAMP``,
``SECOND_APPROVER_REQUIRED``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from domain.errors import DomainError

__all__ = ["Approval", "require_aware", "require_reason", "second_approval"]


def require_reason(reason: str | None, reason_code: str | None = None) -> str:
    """Return the stripped free-text reason; refuse when neither text nor code is given.

    Raises:
        DomainError: ``REASON_REQUIRED`` when both are missing or blank.
    """
    text = (reason or "").strip()
    code = (reason_code or "").strip()
    if not text and not code:
        raise DomainError("REASON_REQUIRED", "A reason is required for this action")
    return text


def require_aware(at: datetime, name: str = "at") -> datetime:
    """Return ``at`` if it is a timezone-aware datetime (``INVALID_TIMESTAMP`` otherwise)."""
    if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
        raise DomainError("INVALID_TIMESTAMP", f"{name} must be a timezone-aware datetime")
    return at


@dataclass(frozen=True, slots=True)
class Approval:
    """A decision by a named user at a known time for a stated reason.

    Attributes:
        approver_id: Primary key of the user who decided (the actor for cancellations).
        at: When, timezone-aware.
        reason: Free text; may be blank only when ``reason_code`` is given.
        reason_code: Code from the configurable reason list, if one was picked.
    """

    approver_id: int
    at: datetime
    reason: str = ""
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.approver_id, bool)
            or not isinstance(self.approver_id, int)
            or self.approver_id < 1
        ):
            raise DomainError("APPROVER_REQUIRED", "An approving user is required")
        require_aware(self.at)
        require_reason(self.reason, self.reason_code)

    @property
    def reason_text(self) -> str:
        """The free-text reason without surrounding whitespace."""
        return self.reason.strip()


def second_approval(
    actor_id: int,
    approver_id: int | None,
    at: datetime,
    reason: str = "",
    reason_code: str | None = None,
) -> Approval:
    """The approval of a second person: someone other than the actor decided (ADR 0018).

    Used where one person must never both do and approve an action (an admission cancelled
    in error, a paid dispense return, a claims rebill or write-off under the policy switch).

    Raises:
        DomainError: ``SECOND_APPROVER_REQUIRED`` when there is no approver or the approver is
            the actor; the errors of :class:`Approval` (reason, time).
    """
    if approver_id is None or approver_id == actor_id:
        raise DomainError(
            "SECOND_APPROVER_REQUIRED",
            "Another person must approve this action",
        )
    return Approval(approver_id, at, reason, reason_code)
