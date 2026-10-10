"""Patient portal rules (FEATURES 15.1, 15.2; ADR 0016). Pure: no Django.

* Access codes: eight digits printed on a receipt, typed by the patient with the file number
  and the phone on file. Stored hashed by the app; here only their shape.
* File numbers and phones: what a patient types is folded to the stored form.
* Receipt verification: an HMAC token over the receipt number (the QR on the printed
  receipt), and the public standing of a receipt (valid, pending, void).
* Sessions: idle and absolute expiry.
* Booking and cancelling an appointment from the portal: which slots a patient may take and
  until when a booking may be cancelled.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from domain.errors import DomainError
from domain.numbering import format_document_number
from domain.payments import Verification

__all__ = [
    "ACCESS_CODE_LENGTH",
    "BookingRules",
    "ReceiptStatus",
    "bookable",
    "can_cancel",
    "check_booking",
    "check_cancel",
    "format_access_code",
    "generate_access_code",
    "initials",
    "mask_phone",
    "normalize_access_code",
    "normalize_file_no",
    "phones_match",
    "public_receipt_status",
    "receipt_token",
    "receipt_token_matches",
    "session_expired",
]

ACCESS_CODE_LENGTH = 8
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_CODE_SEPARATORS = re.compile(r"[\s\-_.]")


def _fold_digits(text: str) -> str:
    return text.translate(_ARABIC_DIGITS)


# --- access codes ------------------------------------------------------------------------


def generate_access_code(randrange: Callable[[int], int]) -> str:
    """A new code: ``ACCESS_CODE_LENGTH`` decimal digits from ``randrange`` (pass
    ``secrets.randbelow`` in production), leading zeros kept."""
    return f"{randrange(10**ACCESS_CODE_LENGTH):0{ACCESS_CODE_LENGTH}d}"


def format_access_code(code: str) -> str:
    """Printed form: two groups of four (``"0123 4567"``)."""
    return f"{code[:4]} {code[4:]}"


def normalize_access_code(text: str) -> str | None:
    """The code a patient typed (spaces, dashes and Arabic-Indic digits allowed), or None
    when it cannot be a code."""
    folded = _CODE_SEPARATORS.sub("", _fold_digits(text or ""))
    if len(folded) != ACCESS_CODE_LENGTH or not (folded.isascii() and folded.isdigit()):
        return None
    return folded


# --- identity ----------------------------------------------------------------------------

_FILE_NO = re.compile(r"^(?:PT-?)?(\d{4})-?(\d{1,10})$")


def normalize_file_no(text: str) -> str:
    """Fold a typed file number to the stored ``PT-YYYY-NNNNNN`` form.

    Case, spaces, Arabic-Indic digits, a missing ``PT-`` prefix and missing zero padding are
    forgiven (``"2026-12"`` is ``"PT-2026-000012"``). Anything else is returned upper-cased
    and without spaces, and simply matches no file.
    """
    compact = re.sub(r"\s+", "", _fold_digits(text or "")).upper()
    found = _FILE_NO.match(compact)
    if found is None:
        return compact
    return format_document_number("PT", int(found.group(1)), int(found.group(2)))


def phones_match(given: str, stored: Iterable[str]) -> bool:
    """True when the normalized phone a patient typed is one of the file's numbers.

    Both sides are already normalized (digits, ``+249``/``00249`` folded to ``0``). Equal
    numbers match, and so do numbers whose last nine digits agree (``912345678`` typed
    without the leading zero, or ``249...`` without the plus).
    """
    if len(given) < 9:
        return False
    for number in stored:
        if not number:
            continue
        if number == given or (len(number) >= 9 and number[-9:] == given[-9:]):
            return True
    return False


def mask_phone(phone: str) -> str:
    """All but the last three digits hidden."""
    if len(phone) <= 3:
        return "•" * len(phone)
    return "•" * (len(phone) - 3) + phone[-3:]


def initials(name: str) -> str:
    """At most the first letters of the first two words (``"A. H."``): enough to recognise a
    receipt as one's own without naming anyone on a public page."""
    letters = [word[0] for word in (name or "").split() if word[0].isalpha()][:2]
    # Some letters upper-case to two ("ß" -> "SS"); keep those as they are.
    return " ".join(f"{ch.upper() if len(ch.upper()) == 1 else ch}." for ch in letters)


# --- receipt verification ----------------------------------------------------------------

_TOKEN_LENGTH = 20


def receipt_token(key: bytes, number: str) -> str:
    """The verification token printed in a receipt's QR: 20 base32 characters (100 bits) of
    HMAC-SHA256 over the receipt number. Only the server, holding ``key``, can make one."""
    mac = hmac.new(
        key, b"hospital.portal.receipt:" + number.strip().upper().encode(), hashlib.sha256
    )
    return base64.b32encode(mac.digest()).decode("ascii")[:_TOKEN_LENGTH].lower()


def receipt_token_matches(key: bytes, number: str, token: str) -> bool:
    """Constant-time check of a scanned token against the receipt number."""
    expected = receipt_token(key, number)
    return hmac.compare_digest(expected.encode(), (token or "").strip().lower().encode())


class ReceiptStatus(StrEnum):
    """What the public verification page says about a receipt."""

    VALID = "valid"
    PENDING = "pending"  # a transfer the bank has not confirmed yet
    VOID = "void"  # a rejected transfer, a reversed payment or a reversal row


def public_receipt_status(
    verification: Verification, *, reversed_: bool, is_reversal: bool
) -> ReceiptStatus:
    if verification is Verification.REJECTED or reversed_ or is_reversal:
        return ReceiptStatus.VOID
    if verification is Verification.PENDING:
        return ReceiptStatus.PENDING
    return ReceiptStatus.VALID


# --- sessions ----------------------------------------------------------------------------


def _require_aware(*moments: datetime) -> None:
    for moment in moments:
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("times must be timezone-aware")


def session_expired(
    created_at: datetime,
    last_seen_at: datetime,
    now: datetime,
    *,
    idle: timedelta,
    absolute: timedelta,
) -> bool:
    """A portal session ends ``idle`` after its last use, and ``absolute`` after it began
    however much it is used."""
    _require_aware(created_at, last_seen_at, now)
    return now >= last_seen_at + idle or now >= created_at + absolute


# --- booking -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BookingRules:
    """``lead``: earliest start after now; ``horizon_days``: last bookable local day after
    today; ``max_open``: future bookings a person may hold; ``cancel_cutoff``: a booking is
    cancelled online at least this long before it starts."""

    lead: timedelta
    horizon_days: int
    max_open: int
    cancel_cutoff: timedelta

    def __post_init__(self) -> None:
        if self.horizon_days < 1:
            raise ValueError("horizon_days must be >= 1")
        if self.max_open < 1:
            raise ValueError("max_open must be >= 1")
        if self.lead < timedelta(0) or self.cancel_cutoff < timedelta(0):
            raise ValueError("lead and cancel_cutoff must not be negative")


def _in_window(
    start: datetime, start_day: date, *, now: datetime, today: date, rules: BookingRules
) -> bool:
    return start >= now + rules.lead and start_day <= today + timedelta(days=rules.horizon_days)


def bookable(
    starts: Iterable[datetime],
    *,
    now: datetime,
    today: date,
    rules: BookingRules,
    day_of: Callable[[datetime], date],
) -> list[datetime]:
    """The free slot starts a patient may book (``day_of`` gives a start's local day)."""
    return [s for s in starts if _in_window(s, day_of(s), now=now, today=today, rules=rules)]


def check_booking(
    start: datetime,
    *,
    now: datetime,
    today: date,
    start_day: date,
    offered: Collection[datetime],
    open_count: int,
    same_day_with_doctor: bool,
    rules: BookingRules,
) -> None:
    """Refuse a portal booking that breaks a rule.

    ``offered`` are the doctor's free schedule slots of that day; ``open_count`` the person's
    future bookings; ``same_day_with_doctor`` whether they already hold one with this doctor
    on that day.

    Raises:
        DomainError: ``PORTAL_SLOT_UNAVAILABLE`` (not a free slot, too soon or too far),
            ``PORTAL_BOOKING_LIMIT`` (``details.limit``), ``PORTAL_ALREADY_BOOKED``.
    """
    _require_aware(start, now)
    if start not in offered or not _in_window(start, start_day, now=now, today=today, rules=rules):
        raise DomainError("PORTAL_SLOT_UNAVAILABLE", "That time cannot be booked online")
    if open_count >= rules.max_open:
        raise DomainError(
            "PORTAL_BOOKING_LIMIT",
            "Too many upcoming appointments are booked already",
            limit=rules.max_open,
        )
    if same_day_with_doctor:
        raise DomainError(
            "PORTAL_ALREADY_BOOKED", "There is already a booking with this doctor on that day"
        )


def can_cancel(starts_at: datetime, *, booked: bool, now: datetime, rules: BookingRules) -> bool:
    _require_aware(starts_at, now)
    return booked and starts_at - now >= rules.cancel_cutoff


def check_cancel(starts_at: datetime, *, booked: bool, now: datetime, rules: BookingRules) -> None:
    """Raises:
    DomainError: ``APPOINTMENT_NOT_BOOKED``, ``PORTAL_CANCEL_TOO_LATE``.
    """
    if not booked:
        raise DomainError("APPOINTMENT_NOT_BOOKED", "The appointment is not open")
    if not can_cancel(starts_at, booked=booked, now=now, rules=rules):
        raise DomainError(
            "PORTAL_CANCEL_TOO_LATE",
            "It is too late to cancel online; please call the center",
            cutoff_hours=int(rules.cancel_cutoff.total_seconds() // 3600),
        )
