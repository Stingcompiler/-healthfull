"""Patient portal rules (FEATURES 15.1, 15.2; ADR 0016): access codes, file numbers, phones,
initials, receipt tokens, sessions, booking and cancellation windows."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.errors import DomainError
from domain.payments import Verification
from domain.portal import (
    ACCESS_CODE_LENGTH,
    BookingRules,
    ReceiptStatus,
    bookable,
    can_cancel,
    check_booking,
    check_cancel,
    format_access_code,
    generate_access_code,
    initials,
    mask_phone,
    normalize_access_code,
    normalize_file_no,
    phones_match,
    public_receipt_status,
    receipt_token,
    receipt_token_matches,
    session_expired,
)

T0 = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
RULES = BookingRules(
    lead=timedelta(minutes=60), horizon_days=30, max_open=3, cancel_cutoff=timedelta(hours=2)
)
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"


# --- access codes ------------------------------------------------------------------------


def test_generated_codes_are_eight_digits() -> None:
    rng = random.Random(7)
    for _ in range(200):
        code = generate_access_code(rng.randrange)
        assert len(code) == ACCESS_CODE_LENGTH == 8
        assert code.isdigit()
        assert code.isascii()


def test_generated_codes_spread_over_the_whole_space() -> None:
    rng = random.Random(1)
    codes = {generate_access_code(rng.randrange) for _ in range(500)}
    assert len(codes) == 500
    assert any(c.startswith("0") for c in codes)  # leading zeros kept


@given(st.text(alphabet="0123456789", min_size=8, max_size=8))
def test_formatted_and_typed_forms_normalize_back(code: str) -> None:
    assert normalize_access_code(code) == code
    assert normalize_access_code(format_access_code(code)) == code
    assert normalize_access_code(f" {code[:4]}-{code[4:]} ") == code
    arabic = code.translate(str.maketrans("0123456789", ARABIC_DIGITS))
    assert normalize_access_code(arabic) == code


@pytest.mark.parametrize(
    "raw", ["", "1234567", "123456789", "12a45678", "１２３４５６７８x", "    "]
)
def test_malformed_codes_normalize_to_none(raw: str) -> None:
    assert normalize_access_code(raw) is None


def test_format_groups_in_fours() -> None:
    assert format_access_code("01234567") == "0123 4567"


# --- file numbers and phones -------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PT-2026-000012", "PT-2026-000012"),
        ("pt-2026-000012", "PT-2026-000012"),
        (" PT 2026 000012 ", "PT-2026-000012"),
        ("2026-12", "PT-2026-000012"),
        ("202600012", "PT-2026-000012"),
        ("PT2026000012", "PT-2026-000012"),
        ("٢٠٢٦-٠٠٠٠١٢", "PT-2026-000012"),
        ("X-99", "X-99"),
        ("PT-2026-000000", "PT-2026-000000"),
        ("0000-1", "0000-1"),
        ("", ""),
    ],
)
def test_file_numbers_accept_loose_input(raw: str, expected: str) -> None:
    assert normalize_file_no(raw) == expected


@given(st.integers(min_value=2000, max_value=2099), st.integers(min_value=1, max_value=999_999))
def test_file_number_forms_agree(year: int, seq: int) -> None:
    canonical = f"PT-{year}-{seq:06d}"
    assert normalize_file_no(canonical) == canonical
    assert normalize_file_no(f"{year}-{seq}") == canonical
    assert normalize_file_no(canonical.lower()) == canonical


def test_phones_match_on_equal_normalized_numbers() -> None:
    assert phones_match("0912345678", ["0912345678", ""])
    assert phones_match("0912345678", ["", "0912345678"])


def test_phones_match_on_the_last_nine_digits() -> None:
    assert phones_match("912345678", ["0912345678"])
    assert phones_match("249912345678", ["0912345678"])


@pytest.mark.parametrize(
    ("given_phone", "stored"),
    [
        ("", ["0912345678"]),
        ("0912345678", ["", ""]),
        ("12345", ["0000012345"]),
        ("0912345679", ["0912345678"]),
    ],
)
def test_phones_do_not_match(given_phone: str, stored: list[str]) -> None:
    assert not phones_match(given_phone, stored)


def test_mask_phone_keeps_the_last_three_digits() -> None:
    assert mask_phone("0912345678") == "•••••••678"
    assert mask_phone("") == ""
    assert mask_phone("12") == "••"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Amna Hassan Ali Mohamed", "A. H."),
        ("آمنة حسن علي", "آ. ح."),
        ("  mohamed  ", "M."),
        ("", ""),
    ],
)
def test_initials_show_at_most_two_letters(name: str, expected: str) -> None:
    assert initials(name) == expected


@given(st.text(min_size=0, max_size=80))
def test_initials_never_reveal_more_than_two_letters(name: str) -> None:
    out = initials(name)
    assert sum(ch.isalpha() for ch in out) <= 2


# --- receipt verification ----------------------------------------------------------------

KEY = b"test-secret-key"


@given(st.from_regex(r"PAY-20[0-9]{2}-[0-9]{6}", fullmatch=True))
def test_receipt_tokens_verify_their_own_number_only(number: str) -> None:
    token = receipt_token(KEY, number)
    assert len(token) == 20
    assert token.isalnum()
    assert token == token.lower()
    assert receipt_token_matches(KEY, number, token)
    assert receipt_token_matches(KEY, number.lower(), token.upper())
    assert not receipt_token_matches(KEY, number + "1", token)
    assert not receipt_token_matches(b"another-key", number, token)


@pytest.mark.parametrize("token", ["", "x" * 20, "a" * 200])
def test_wrong_tokens_never_match(token: str) -> None:
    assert not receipt_token_matches(KEY, "PAY-2026-000001", token)


@pytest.mark.parametrize(
    ("verification", "reversed_", "is_reversal", "expected"),
    [
        (Verification.CONFIRMED, False, False, ReceiptStatus.VALID),
        (Verification.PENDING, False, False, ReceiptStatus.PENDING),
        (Verification.REJECTED, False, False, ReceiptStatus.VOID),
        (Verification.CONFIRMED, True, False, ReceiptStatus.VOID),
        (Verification.PENDING, True, False, ReceiptStatus.VOID),
        (Verification.CONFIRMED, False, True, ReceiptStatus.VOID),
    ],
)
def test_public_receipt_status(
    verification: Verification, reversed_: bool, is_reversal: bool, expected: ReceiptStatus
) -> None:
    assert (
        public_receipt_status(verification, reversed_=reversed_, is_reversal=is_reversal)
        is expected
    )


# --- sessions ----------------------------------------------------------------------------

IDLE = timedelta(minutes=15)
ABSOLUTE = timedelta(hours=4)


def test_session_lives_while_used() -> None:
    assert not session_expired(
        T0, T0 + timedelta(minutes=10), T0 + timedelta(minutes=24), idle=IDLE, absolute=ABSOLUTE
    )


def test_session_idles_out() -> None:
    assert session_expired(T0, T0, T0 + IDLE, idle=IDLE, absolute=ABSOLUTE)


def test_session_ends_at_the_absolute_limit_even_when_used() -> None:
    last = T0 + ABSOLUTE - timedelta(seconds=1)
    assert session_expired(T0, last, T0 + ABSOLUTE, idle=IDLE, absolute=ABSOLUTE)


@given(st.integers(min_value=0, max_value=6 * 3600), st.integers(min_value=0, max_value=6 * 3600))
def test_session_expiry_is_monotonic(used_after: int, checked_after: int) -> None:
    last = T0 + timedelta(seconds=used_after)
    now = last + timedelta(seconds=checked_after)
    expired = session_expired(T0, last, now, idle=IDLE, absolute=ABSOLUTE)
    later = session_expired(T0, last, now + timedelta(seconds=1), idle=IDLE, absolute=ABSOLUTE)
    assert later or not expired  # once expired, always expired


def test_session_times_must_be_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        session_expired(T0.replace(tzinfo=None), T0, T0, idle=IDLE, absolute=ABSOLUTE)


# --- booking ---------------------------------------------------------------------------------


def _slot(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


def _book(start: datetime, **kw: object) -> None:
    args: dict[str, object] = {
        "now": T0,
        "today": T0.date(),
        "start_day": start.date(),
        "offered": [start],
        "open_count": 0,
        "same_day_with_doctor": False,
        "rules": RULES,
    }
    args.update(kw)
    check_booking(start, **args)  # type: ignore[arg-type]


def test_a_free_future_slot_books() -> None:
    _book(_slot(3))


def test_a_slot_not_offered_is_unavailable() -> None:
    with pytest.raises(DomainError) as err:
        _book(_slot(3), offered=[_slot(4)])
    assert err.value.code == "PORTAL_SLOT_UNAVAILABLE"


def test_a_slot_inside_the_lead_time_is_unavailable() -> None:
    with pytest.raises(DomainError) as err:
        _book(_slot(0.5))
    assert err.value.code == "PORTAL_SLOT_UNAVAILABLE"


def test_a_slot_beyond_the_horizon_is_unavailable() -> None:
    far = _slot(24 * 31)
    with pytest.raises(DomainError) as err:
        _book(far)
    assert err.value.code == "PORTAL_SLOT_UNAVAILABLE"
    _book(_slot(24 * 30))  # the last day of the horizon still books


def test_open_bookings_are_limited() -> None:
    _book(_slot(3), open_count=2)
    with pytest.raises(DomainError) as err:
        _book(_slot(3), open_count=3)
    assert err.value.code == "PORTAL_BOOKING_LIMIT"
    assert err.value.details == {"limit": 3}


def test_one_booking_per_doctor_and_day() -> None:
    with pytest.raises(DomainError) as err:
        _book(_slot(3), same_day_with_doctor=True)
    assert err.value.code == "PORTAL_ALREADY_BOOKED"


@given(st.lists(st.integers(min_value=-48 * 60, max_value=40 * 24 * 60), max_size=40))
def test_bookable_keeps_exactly_the_slots_check_booking_accepts(minutes: list[int]) -> None:
    starts = [T0 + timedelta(minutes=m) for m in minutes]
    kept = bookable(starts, now=T0, today=T0.date(), rules=RULES, day_of=lambda d: d.date())
    for start in starts:
        try:
            _book(start, offered=starts)
            accepted = True
        except DomainError:
            accepted = False
        assert (start in kept) == accepted


# --- cancellation ----------------------------------------------------------------------------


def test_cancel_before_the_cutoff() -> None:
    assert can_cancel(_slot(3), booked=True, now=T0, rules=RULES)
    check_cancel(_slot(3), booked=True, now=T0, rules=RULES)


def test_cancel_at_or_after_the_cutoff_is_too_late() -> None:
    assert not can_cancel(_slot(2), booked=True, now=T0 + timedelta(seconds=1), rules=RULES)
    with pytest.raises(DomainError) as err:
        check_cancel(_slot(1), booked=True, now=T0, rules=RULES)
    assert err.value.code == "PORTAL_CANCEL_TOO_LATE"


def test_cancel_needs_an_open_booking() -> None:
    assert not can_cancel(_slot(5), booked=False, now=T0, rules=RULES)
    with pytest.raises(DomainError) as err:
        check_cancel(_slot(5), booked=False, now=T0, rules=RULES)
    assert err.value.code == "APPOINTMENT_NOT_BOOKED"


@given(st.integers(min_value=-72 * 60, max_value=72 * 60))
def test_can_cancel_agrees_with_check_cancel(minutes_ahead: int) -> None:
    start = T0 + timedelta(minutes=minutes_ahead)
    try:
        check_cancel(start, booked=True, now=T0, rules=RULES)
        ok = True
    except DomainError:
        ok = False
    assert can_cancel(start, booked=True, now=T0, rules=RULES) == ok
    assert ok == (start - T0 >= RULES.cancel_cutoff)


def test_rules_reject_nonsense() -> None:
    with pytest.raises(ValueError, match="horizon_days"):
        BookingRules(lead=timedelta(0), horizon_days=0, max_open=1, cancel_cutoff=timedelta(0))
    with pytest.raises(ValueError, match="max_open"):
        BookingRules(lead=timedelta(0), horizon_days=1, max_open=0, cancel_cutoff=timedelta(0))


def test_horizon_is_counted_in_local_days() -> None:
    today = date(2026, 10, 10)
    start = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
    check_booking(
        start,
        now=T0,
        today=today,
        start_day=date(2026, 11, 9),
        offered=[start],
        open_count=0,
        same_day_with_doctor=False,
        rules=RULES,
    )


# --- the staff receipt check reads the portal QR -------------------------------------------


def test_staff_check_reads_the_number_from_the_portal_qr() -> None:
    from domain.payments import parse_receipt_code

    url = "http://192.168.1.10/verify/abcdefghijklmnopqrst?r=RCP-2026-000012"
    code = parse_receipt_code(url)
    assert code.number == "RCP-2026-000012"
    assert code.amount is None
    assert code.day is None
    assert parse_receipt_code("RCP-2026-000012|15000.00|2026-10-10").number == "RCP-2026-000012"
