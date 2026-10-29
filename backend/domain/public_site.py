"""Public site switches and online booking settings (ADR 0028, 0029). Pure: no Django.

Three administrator switches decide what the public reaches: ``site`` (the center website),
``online_booking`` (the booking reads and writes) and ``patient_tracking`` (portal sign-in and
every patient operation). They are enforced by the service layer through :func:`require_site`,
:func:`require_online_booking` and :func:`require_tracking`, never only in the UI.

The booking rules live in the same settings row (they were environment settings before
Phase 1). :data:`RULE_RANGES` is the single source of their limits: the model validators and
the admin screen use it. :func:`initial_values` is what the creating migration writes, and the
only place the "new install versus existing install" choice is made (ADR 0029 K1).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from types import MappingProxyType

from domain.errors import DomainError
from domain.portal import BookingRules


@dataclass(frozen=True, slots=True)
class Switches:
    site: bool
    online_booking: bool
    patient_tracking: bool


def require_site(switches: Switches) -> None:
    """Raises: DomainError ``SITE_DISABLED`` (answered 404) while the website is off."""
    if not switches.site:
        raise DomainError("SITE_DISABLED", "The center website is switched off")


def require_online_booking(switches: Switches) -> None:
    """Raises: DomainError ``ONLINE_BOOKING_DISABLED`` while online booking is off."""
    if not switches.online_booking:
        raise DomainError("ONLINE_BOOKING_DISABLED", "Online booking is switched off")


def require_tracking(switches: Switches) -> None:
    """Raises: DomainError ``PORTAL_DISABLED`` while patient sign-in and tracking are off."""
    if not switches.patient_tracking:
        raise DomainError("PORTAL_DISABLED", "Patient sign-in is switched off")


def tracking_turned_off(before: Switches, after: Switches) -> bool:
    """Whether a save switches tracking off, so every live portal session must end."""
    return before.patient_tracking and not after.patient_tracking


#: Inclusive (min, max) of every whole-number setting. Phase 1 enforced the first four;
#: Phase 3 the reschedule cut-off, the request lifetime and the review window; the others
#: are stored now and take effect with the phases that use them (ADR 0029).
RULE_RANGES: Mapping[str, tuple[int, int]] = MappingProxyType(
    {
        "lead_minutes": (0, 7 * 24 * 60),
        "horizon_days": (1, 365),
        "max_open": (1, 20),
        "cancel_cutoff_hours": (0, 7 * 24),
        "reschedule_cutoff_hours": (0, 7 * 24),
        "request_ttl_hours": (1, 7 * 24),
        "max_guest_bookings_per_phone": (1, 10),
        "max_pending_per_doctor_day": (1, 200),
        "max_requests_per_address_day": (1, 1000),
        "pow_difficulty_bits": (0, 26),
        "guest_retention_days": (1, 3650),
        "min_review_minutes": (0, 24 * 60),
    }
)

#: Defaults of the whole-number settings (the owner accepted the abuse limits on 2026-10-29).
RULE_DEFAULTS: Mapping[str, int] = MappingProxyType(
    {
        "lead_minutes": 60,
        "horizon_days": 30,
        "max_open": 3,
        "cancel_cutoff_hours": 2,
        "reschedule_cutoff_hours": 2,
        "request_ttl_hours": 24,
        "max_guest_bookings_per_phone": 2,
        "max_pending_per_doctor_day": 10,
        "max_requests_per_address_day": 5,
        "pow_difficulty_bits": 18,
        "guest_retention_days": 90,
        "min_review_minutes": 30,
    }
)

#: The environment settings the four Phase 1 rules came from; their values at migration time
#: become the row's first values (ADR 0029 B).
LEGACY_ENV: Mapping[str, str] = MappingProxyType(
    {
        "lead_minutes": "PORTAL_BOOKING_LEAD_MINUTES",
        "horizon_days": "PORTAL_BOOKING_HORIZON_DAYS",
        "max_open": "PORTAL_MAX_OPEN_APPOINTMENTS",
        "cancel_cutoff_hours": "PORTAL_CANCEL_CUTOFF_HOURS",
    }
)


def clamp(name: str, value: int) -> int:
    low, high = RULE_RANGES[name]
    return min(max(value, low), high)


def _legacy_int(raw: str | None, default: int) -> int:
    try:
        return int(str(raw).strip()) if raw is not None else default
    except ValueError:
        return default


def initial_values(*, existing_install: bool, env: Mapping[str, str]) -> dict[str, int | bool]:
    """The settings row the creating migration writes (ADR 0029 K1).

    A **new install** (no patient file yet) starts with every switch off and approval on. An
    **existing install** keeps what it had before the switches existed: the patient portal and
    its booking stay on, booking stays instant (approval off) until the administrator turns
    approval on; the website stays off so ``/`` does not change until an administrator
    switches it on (ADR 0028 decision 4). The four legacy rules take their environment values,
    pulled into range; a malformed value falls back to the default.
    """
    values: dict[str, int | bool] = dict(RULE_DEFAULTS)
    for name, variable in LEGACY_ENV.items():
        values[name] = clamp(name, _legacy_int(env.get(variable), RULE_DEFAULTS[name]))
    values.update(
        site_enabled=False,
        online_booking_enabled=existing_install,
        patient_tracking_enabled=existing_install,
        require_approval=not existing_install,
        reschedule_allowed=True,
        guest_booking_enabled=True,
    )
    return values


def booking_rules(
    *,
    lead_minutes: int,
    horizon_days: int,
    max_open: int,
    cancel_cutoff_hours: int,
    reschedule_allowed: bool = True,
    reschedule_cutoff_hours: int = RULE_DEFAULTS["reschedule_cutoff_hours"],
) -> BookingRules:
    """The portal booking rules of the settings row (``domain.portal.BookingRules``)."""
    return BookingRules(
        lead=timedelta(minutes=lead_minutes),
        horizon_days=horizon_days,
        max_open=max_open,
        cancel_cutoff=timedelta(hours=cancel_cutoff_hours),
        reschedule_allowed=reschedule_allowed,
        reschedule_cutoff=timedelta(hours=reschedule_cutoff_hours),
    )


@dataclass(frozen=True, slots=True)
class RequestRules:
    """How an online booking waits for reception (ADR 0029 A2, A8, C): whether it does,
    how long a request lives, and the shortest time reception must have to answer it."""

    require_approval: bool
    ttl: timedelta
    min_review: timedelta


def request_rules(
    *, require_approval: bool, request_ttl_hours: int, min_review_minutes: int
) -> RequestRules:
    return RequestRules(
        require_approval=require_approval,
        ttl=timedelta(hours=request_ttl_hours),
        min_review=timedelta(minutes=min_review_minutes),
    )


def offered_booking_rules(rules: BookingRules, requests: RequestRules) -> BookingRules:
    """The rules for what the portal offers: while online bookings wait for approval, the
    earliest offered start also leaves reception its review window (``start - lead - now``
    at least ``min_review``, ADR 0029 C), so a request is never born expired."""
    if not requests.require_approval:
        return rules
    return replace(rules, lead=rules.lead + requests.min_review)
