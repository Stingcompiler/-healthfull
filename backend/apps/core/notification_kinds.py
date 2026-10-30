"""Every in-app notification kind: who receives it and which screens resolve it (FEATURES 0.13).

The single source for recipients and links. ``notify_kind`` (``apps.core.services``) sends a
kind to its recipients from here, so a module cannot alert people the table does not name.
Each kind lists the screens that resolve it in order of preference, each with the permission
that screen's endpoints require; the bell (``frontend/src/features/notifications/kinds.ts``,
whose contract test reads this file) opens the first one the reader may open, and none when
they may open none. ``apps/core/tests/test_notification_kinds.py`` proves that every default
recipient may open at least one of its kind's screens.

Keep each entry in the literal form ``NotificationKind("<code>", ..., links=(Link("<route>",
"<permission>"), ...))``: the frontend test parses it.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.core.roles import ACCOUNTANT, CASHIER_SUPERVISOR, MANAGER, PHARMACIST, RECEPTIONIST

__all__ = ["KINDS", "Link", "NotificationKind", "kind"]


@dataclass(frozen=True, slots=True)
class Link:
    #: A route of the SPA (TanStack path, ``$param`` for ids from the payload).
    route: str
    #: The permission the screen's endpoints require.
    permission: str


@dataclass(frozen=True, slots=True)
class NotificationKind:
    code: str
    #: Recipients by role (managers, verifiers, pharmacists).
    roles: frozenset[str] = frozenset()
    #: Recipients by permission: every active holder at the time it is sent.
    holders_of: str = ""
    #: Recipients chosen per event (the ordering doctor): the permission every such person
    #: holds by their role, used only to prove the link opens for them.
    users_holding: str = ""
    links: tuple[Link, ...] = ()


#: Managers and cashier supervisors: money that went wrong (FLOW step 9).
MONEY_WATCH = frozenset({MANAGER, CASHIER_SUPERVISOR})
#: Who verifies transfers (FEATURES 6.4).
VERIFIERS = frozenset({CASHIER_SUPERVISOR, ACCOUNTANT})

_ENTRIES: tuple[NotificationKind, ...] = (
    NotificationKind(
        "lab_result_ready",
        users_holding="orders.create",
        links=(Link("/clinic/visits/$visitId", "clinical.view"),),
    ),
    NotificationKind(
        "lab_result_critical",
        users_holding="orders.create",
        links=(Link("/clinic/visits/$visitId", "clinical.view"),),
    ),
    NotificationKind(
        "stock_low",
        roles=frozenset({PHARMACIST}),
        links=(Link("/pharmacy/low-stock", "pharmacy.view"),),
    ),
    NotificationKind(
        "stock_low_summary",
        holders_of="pharmacy.receive_goods",
        links=(Link("/pharmacy/low-stock", "pharmacy.view"),),
    ),
    NotificationKind(
        "transfers_pending_overdue",
        roles=VERIFIERS,
        links=(Link("/cashier/transfers", "payments.confirm_transfer"),),
    ),
    NotificationKind(
        "transfer_rejected",
        roles=MONEY_WATCH,
        links=(
            Link("/cashier/transfers", "payments.confirm_transfer"),
            Link("/patients/$patientId", "patients.view"),
        ),
    ),
    NotificationKind(
        "patient_credit_negative",
        roles=MONEY_WATCH,
        links=(Link("/patients/$patientId", "patients.view"),),
    ),
    NotificationKind(
        "shift_variance",
        roles=MONEY_WATCH,
        links=(Link("/cashier/review", "payments.review_shift"),),
    ),
    NotificationKind(
        "shift_review_pending",
        holders_of="payments.review_shift",
        links=(Link("/cashier/review", "payments.review_shift"),),
    ),
    NotificationKind(
        "backup_stale",
        holders_of="ops.view_status",
        links=(Link("/administration/system", "ops.view_status"),),
    ),
    NotificationKind(
        "integrity_failed",
        holders_of="ops.view_status",
        links=(Link("/administration/system", "ops.view_status"),),
    ),
    # Online booking (ADR 0029 I): receptionists answer requests in the reception inbox
    # (Phase 4b, /visits/online-bookings).
    NotificationKind(
        "online_booking_requested",
        roles=frozenset({RECEPTIONIST}),
        links=(Link("/visits/online-bookings", "visits.manage_online_bookings"),),
    ),
    NotificationKind(
        "online_booking_cancelled_by_patient",
        roles=frozenset({RECEPTIONIST}),
        links=(Link("/visits/online-bookings", "visits.manage_online_bookings"),),
    ),
)

KINDS: dict[str, NotificationKind] = {k.code: k for k in _ENTRIES}


def kind(code: str) -> NotificationKind:
    """The registered kind ``code``.

    Raises:
        KeyError: an unregistered kind (a programming error: add it to ``_ENTRIES``).
    """
    return KINDS[code]
