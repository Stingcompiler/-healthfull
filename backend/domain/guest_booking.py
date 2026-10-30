"""Guest booking without a file (ADR 0029 D, F, G; plan Phase 4). Pure: no Django.

* **Reference and PIN.** A guest booking is opened with a reference of 10 base32 characters
  (50 bits, from ``secrets``) and a 6-digit PIN shown once; the PIN is stored only as a password
  hash by the service. What a guest types is folded here (spaces, dashes, lower case,
  Arabic-Indic digits) before it is compared.
* **Phone.** The phone is unverified (no SMS). :func:`phone_key` folds a typed number to the
  international digits a ``wa.me`` link needs (Sudanese local numbers fold to ``249...``), and
  the same key compares two numbers for the per-phone cap and the bulk reject.
* **Caps.** :func:`check_guest_caps` refuses a guest request past the per-phone, per-doctor-day
  and per-address limits of the settings row (ADR 0029 F).
* **WhatsApp.** :func:`whatsapp_url` and :func:`status_message` build the click-to-chat link of
  the reception inbox: a plain ``https://wa.me/<digits>?text=...`` with the center, doctor,
  time, status and reference, **never the PIN** (ADR 0029 A9). Nothing is sent by the server.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

from domain.errors import DomainError

__all__ = [
    "PIN_LENGTH",
    "REFERENCE_ALPHABET",
    "REFERENCE_LENGTH",
    "BookingFacts",
    "GuestCaps",
    "check_guest_caps",
    "format_reference",
    "generate_pin",
    "generate_reference",
    "normalize_pin",
    "normalize_reference",
    "phone_key",
    "require_phone_key",
    "share_message",
    "share_url",
    "status_message",
    "validate_contact_name",
    "whatsapp_url",
]

REFERENCE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"  # RFC 4648 base32
REFERENCE_LENGTH = 10
PIN_LENGTH = 6
NAME_MAX = 200

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_SEPARATORS = re.compile(r"[\s\-_.]")


def _fold(text: str) -> str:
    return _SEPARATORS.sub("", (text or "").translate(_ARABIC_DIGITS))


# --- reference and PIN ---------------------------------------------------------------------


def generate_reference(randbelow: Callable[[int], int]) -> str:
    """A new reference: ``REFERENCE_LENGTH`` base32 characters from ``randbelow`` (pass
    ``secrets.randbelow``)."""
    size = len(REFERENCE_ALPHABET)
    return "".join(REFERENCE_ALPHABET[randbelow(size)] for _ in range(REFERENCE_LENGTH))


def format_reference(reference: str) -> str:
    """Shown in two groups of five (``"ABCDE-FGH23"``), easier to read over the phone."""
    return f"{reference[:5]}-{reference[5:]}"


def normalize_reference(text: str) -> str | None:
    """The reference a guest typed, or None when it cannot be one. Case, spaces and dashes
    are forgiven."""
    folded = _fold(text).upper()
    if len(folded) != REFERENCE_LENGTH or any(ch not in REFERENCE_ALPHABET for ch in folded):
        return None
    return folded


def generate_pin(randbelow: Callable[[int], int]) -> str:
    """A new PIN: ``PIN_LENGTH`` decimal digits, leading zeros kept."""
    return f"{randbelow(10**PIN_LENGTH):0{PIN_LENGTH}d}"


def normalize_pin(text: str) -> str | None:
    """The PIN a guest typed (Arabic-Indic digits and spaces allowed), or None."""
    folded = _fold(text)
    if len(folded) != PIN_LENGTH or not (folded.isascii() and folded.isdigit()):
        return None
    return folded


# --- contact -------------------------------------------------------------------------------


def validate_contact_name(raw: str) -> str:
    """The guest's name, spaces collapsed.

    Raises:
        DomainError: ``GUEST_NAME_REQUIRED`` (empty or longer than 200 characters).
    """
    name = " ".join((raw or "").split())
    if not name or len(name) > NAME_MAX:
        raise DomainError("GUEST_NAME_REQUIRED", "Give the name of the person who will come")
    return name


def phone_key(raw: str) -> str | None:
    """International digits of a typed phone, or None when it cannot be a phone.

    Sudanese numbers may be typed locally (``0912 345 678``, ``912345678``) and fold to
    ``249912345678``; ``+`` or ``00`` keeps any other country code; Arabic-Indic digits are
    folded. Two typings of one number give one key (the per-phone cap compares keys).
    """
    text = (raw or "").translate(_ARABIC_DIGITS).strip()
    compact = re.sub(r"[\s\-().]", "", text)
    if compact.startswith("+"):
        digits = compact[1:]
    elif compact.startswith("00"):
        digits = compact[2:]
    elif compact.startswith("0"):
        digits = "249" + compact[1:]
    elif len(compact) == 9:
        digits = "249" + compact
    else:
        digits = compact
    if not (digits.isascii() and digits.isdigit() and 8 <= len(digits) <= 15):
        return None
    return digits


def require_phone_key(raw: str) -> str:
    """Raises: DomainError ``GUEST_PHONE_INVALID`` when ``raw`` is not a phone number."""
    key = phone_key(raw)
    if key is None:
        raise DomainError("GUEST_PHONE_INVALID", "Give a phone number like 0912 345 678")
    return key


# --- caps (ADR 0029 F) ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GuestCaps:
    """The administrator's guest limits (settings row)."""

    per_phone: int
    pending_per_doctor_day: int
    per_address_day: int


def check_guest_caps(
    caps: GuestCaps,
    *,
    open_for_phone: int,
    pending_for_doctor_day: int,
    will_be_request: bool,
) -> None:
    """Refuse a guest booking past a cap. ``open_for_phone``: the phone's future bookings that
    hold a slot; ``pending_for_doctor_day``: requests waiting for approval for that doctor on
    that day (counted only when the new booking is a request too).

    Raises:
        DomainError: ``GUEST_PHONE_LIMIT`` (``details.limit``), ``ONLINE_DOCTOR_DAY_FULL``.
    """
    if open_for_phone >= caps.per_phone:
        raise DomainError(
            "GUEST_PHONE_LIMIT",
            "This phone number already has as many open bookings as allowed",
            limit=caps.per_phone,
        )
    if will_be_request and pending_for_doctor_day >= caps.pending_per_doctor_day:
        raise DomainError(
            "ONLINE_DOCTOR_DAY_FULL",
            "This doctor has too many requests waiting on that day; choose another day",
        )


# --- WhatsApp (ADR 0029 A9, G) -------------------------------------------------------------


def whatsapp_url(phone: str, text: str) -> str | None:
    """``https://wa.me/<digits>?text=<text>`` for a typed phone, or None when the phone is not
    a number. Nothing is sent: reception opens the link on its own phone."""
    key = phone_key(phone)
    if key is None:
        return None
    return f"https://wa.me/{key}?text={quote(text, safe='')}"


def share_url(text: str) -> str:
    """``https://wa.me/?text=...`` (no number): the guest picks whom to send it to."""
    return f"https://wa.me/?text={quote(text, safe='')}"


_STATUS_WORDS: dict[str, tuple[str, str]] = {
    "awaiting_approval": ("بانتظار تأكيد الاستقبال", "waiting for reception to confirm"),
    "confirmed": ("مؤكد", "confirmed"),
    "received": ("تم استقبالك", "you were received"),
    "moved": ("نُقل إلى موعد آخر", "moved to another time"),
    "cancelled_by_you": ("أُلغي بطلبك", "cancelled at your request"),
    "cancelled_by_center": ("ألغاه المركز", "cancelled by the center"),
    "declined": ("لم يُقبل الطلب", "not accepted"),
    "expired": ("انتهت مهلة الطلب", "the request expired"),
    "missed": ("لم تحضر", "missed"),
}


@dataclass(frozen=True, slots=True)
class BookingFacts:
    """What a status message tells the booker (never the PIN)."""

    center_ar: str
    center_en: str
    doctor_ar: str
    doctor_en: str
    when: str  # the local date and time, already formatted
    status: str  # a ``domain.portal_status.BookingDisplay`` value
    reference: str = ""  # formatted reference of a guest booking, empty for a patient's


def status_message(facts: BookingFacts) -> str:
    """The prefilled bilingual WhatsApp text: Arabic first, then English."""
    word_ar, word_en = _STATUS_WORDS.get(facts.status, (facts.status, facts.status))
    center_ar = facts.center_ar or facts.center_en
    center_en = facts.center_en or facts.center_ar
    doctor_ar = facts.doctor_ar or facts.doctor_en
    doctor_en = facts.doctor_en or facts.doctor_ar
    ar = f"{center_ar}: حجزك مع {doctor_ar} في {facts.when}: {word_ar}."
    en = f"{center_en}: your booking with {doctor_en} on {facts.when}: {word_en}."
    if facts.reference:
        ar += f" رقم الحجز {facts.reference}."
        en += f" Reference {facts.reference}."
    return f"{ar}\n{en}"


def share_message(*, center_ar: str, center_en: str, reference: str, page: str) -> str:
    """The text a guest may send to themselves or family: the reference and the center's page
    address, never the PIN (ADR 0029 G)."""
    lines = [
        f"{center_ar or center_en}: رقم حجزي {reference}.",
        f"{center_en or center_ar}: my booking reference {reference}.",
    ]
    if page:
        lines.append(page)
    return "\n".join(lines)
