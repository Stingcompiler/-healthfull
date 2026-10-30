"""Portal abuse-control and session settings (ADR 0016). Each reads ``settings.<NAME>`` when
present (``.env`` through ``config.settings`` or a test override), else the default here.

The booking rules (lead time, horizon, open bookings, cancel cut-off) are no longer here: they
live in ``core.PublicSiteSettings`` and the administrator edits them (ADR 0029 B); read them
with ``apps.core.services.booking_rules``."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings

COOKIE_NAME = "hospital_portal"


def _int(name: str, default: int) -> int:
    return int(getattr(settings, name, default))


def code_ttl() -> timedelta:
    """How long a printed access code lets its patient sign in."""
    return timedelta(days=_int("PORTAL_CODE_TTL_DAYS", 30))


def code_max_attempts() -> int:
    """Wrong codes (with the right file number and phone) before a code locks for good."""
    return _int("PORTAL_CODE_MAX_ATTEMPTS", 5)


def session_idle() -> timedelta:
    return timedelta(seconds=_int("PORTAL_SESSION_IDLE_SECONDS", 15 * 60))


def session_absolute() -> timedelta:
    return timedelta(seconds=_int("PORTAL_SESSION_MAX_SECONDS", 4 * 60 * 60))


def file_lock() -> tuple[int, timedelta]:
    """Failed sign-ins per typed file number before it locks, and for how long."""
    return (
        _int("PORTAL_FILE_MAX_FAILURES", 5),
        timedelta(seconds=_int("PORTAL_FILE_LOCK_SECONDS", 15 * 60)),
    )


def ip_rule() -> tuple[int, timedelta]:
    """Failed sign-ins per client address in a window before 429."""
    return (
        _int("PORTAL_LOGIN_IP_MAX_FAILURES", 20),
        timedelta(seconds=_int("PORTAL_LOGIN_IP_WINDOW_SECONDS", 15 * 60)),
    )


def verify_rule() -> tuple[int, timedelta]:
    """Public receipt checks per client address in a window before 429."""
    return (
        _int("PORTAL_VERIFY_IP_MAX", 60),
        timedelta(seconds=_int("PORTAL_VERIFY_IP_WINDOW_SECONDS", 10 * 60)),
    )


def page_rule() -> tuple[int, timedelta]:
    """Public center page and logo reads per client address in a window before 429."""
    return (
        _int("PORTAL_PAGE_IP_MAX", 300),
        timedelta(seconds=_int("PORTAL_PAGE_IP_WINDOW_SECONDS", 10 * 60)),
    )


def cookie_secure() -> bool:
    return bool(getattr(settings, "SESSION_COOKIE_SECURE", False))


GUEST_COOKIE_NAME = "hospital_guest"
#: The guest cookie reaches only the guest operations (ADR 0029 D).
GUEST_COOKIE_PATH = "/api/portal/guest"


def guest_session_idle() -> timedelta:
    return timedelta(seconds=_int("GUEST_SESSION_IDLE_SECONDS", 15 * 60))


def guest_session_absolute() -> timedelta:
    return timedelta(seconds=_int("GUEST_SESSION_MAX_SECONDS", 2 * 60 * 60))


def guest_max_attempts() -> int:
    """Wrong PINs before a guest booking locks until staff issue a new PIN (ADR 0029 D)."""
    return _int("GUEST_PIN_MAX_ATTEMPTS", 5)


def guest_ip_rule() -> tuple[int, timedelta]:
    """Failed guest sign-ins per client address in a window before 429."""
    return (
        _int("GUEST_LOGIN_IP_MAX_FAILURES", 20),
        timedelta(seconds=_int("GUEST_LOGIN_IP_WINDOW_SECONDS", 15 * 60)),
    )


def challenge_ttl() -> timedelta:
    """How long a proof-of-work challenge may be solved and sent (ADR 0029 F)."""
    return timedelta(seconds=_int("BOOKING_CHALLENGE_TTL_SECONDS", 10 * 60))


def idempotency_ttl() -> timedelta:
    """How long the answer of a public booking POST is kept for a retry (ADR 0029 C)."""
    return timedelta(hours=_int("IDEMPOTENCY_TTL_HOURS", 24))
