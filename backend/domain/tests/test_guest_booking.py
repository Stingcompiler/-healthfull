"""Guest booking rules: reference and PIN shape, phone keys, caps, WhatsApp text (ADR 0029 D, F)."""

from __future__ import annotations

import random
from urllib.parse import unquote

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain import guest_booking as g
from domain.errors import DomainError

_AR = "٠١٢٣٤٥٦٧٨٩"


@given(st.randoms(use_true_random=False))
def test_a_reference_is_ten_base32_characters_and_reads_back_however_typed(
    rnd: random.Random,
) -> None:
    ref = g.generate_reference(rnd.randrange)
    assert len(ref) == g.REFERENCE_LENGTH
    assert set(ref) <= set(g.REFERENCE_ALPHABET)
    shown = g.format_reference(ref)
    assert g.normalize_reference(shown) == ref
    assert g.normalize_reference(shown.lower()) == ref
    assert g.normalize_reference(" ".join(ref)) == ref


@given(st.text(max_size=14))
def test_normalize_reference_accepts_only_references(text: str) -> None:
    got = g.normalize_reference(text)
    if got is not None:
        assert len(got) == g.REFERENCE_LENGTH
        assert set(got) <= set(g.REFERENCE_ALPHABET)


@pytest.mark.parametrize(
    "bad", ["", "ABCDE", "ABCDEFGHIJK", "ABCDEFGHI1", "ABCDEFGHI0", "ABCDE-FGHI8"]
)
def test_not_a_reference(bad: str) -> None:
    assert g.normalize_reference(bad) is None


@given(st.integers(min_value=0, max_value=10**6 - 1))
def test_a_pin_keeps_its_zeros_and_folds_arabic_digits(n: int) -> None:
    pin = g.generate_pin(lambda _: n)
    assert len(pin) == g.PIN_LENGTH
    assert pin.isdigit()
    arabic = pin.translate(str.maketrans("0123456789", _AR))
    assert g.normalize_pin(arabic) == pin
    assert g.normalize_pin(f"{pin[:3]} {pin[3:]}") == pin


@pytest.mark.parametrize("bad", ["", "12345", "1234567", "12a456", "١٢٣٤٥"])
def test_not_a_pin(bad: str) -> None:
    assert g.normalize_pin(bad) is None


_sudan = st.from_regex(r"9[0-9]{8}", fullmatch=True)


@given(_sudan)
def test_every_typing_of_a_sudanese_number_has_one_key(local: str) -> None:
    key = "249" + local
    typings = [
        "0" + local,
        local,
        "+249" + local,
        "00249" + local,
        f"0{local[:3]} {local[3:6]} {local[6:]}",
        ("0" + local).translate(str.maketrans("0123456789", _AR)),
        f"+249-{local[:3]}-{local[3:]}",
    ]
    for typed in typings:
        assert g.phone_key(typed) == key, typed


@given(st.text(max_size=30))
def test_a_phone_key_is_digits_and_idempotent(text: str) -> None:
    key = g.phone_key(text)
    if key is not None:
        assert key.isascii()
        assert key.isdigit()
        assert 8 <= len(key) <= 15
        assert g.phone_key("+" + key) == key


@pytest.mark.parametrize("bad", ["", "abc", "12", "+1234567890123456"])
def test_not_a_phone(bad: str) -> None:
    assert g.phone_key(bad) is None
    with pytest.raises(DomainError) as err:
        g.require_phone_key(bad)
    assert err.value.code == "GUEST_PHONE_INVALID"


def test_a_name_is_required_and_bounded() -> None:
    assert g.validate_contact_name("  Amna   Ali ") == "Amna Ali"
    for bad in ("", "   ", "x" * 201):
        with pytest.raises(DomainError) as err:
            g.validate_contact_name(bad)
        assert err.value.code == "GUEST_NAME_REQUIRED"


CAPS = g.GuestCaps(per_phone=2, pending_per_doctor_day=10, per_address_day=5)


@given(
    st.integers(min_value=0, max_value=5),
    st.integers(min_value=0, max_value=15),
    st.booleans(),
)
def test_caps_refuse_exactly_at_their_limit(phone: int, doctor_day: int, request: bool) -> None:
    def run() -> None:
        g.check_guest_caps(
            CAPS, open_for_phone=phone, pending_for_doctor_day=doctor_day, will_be_request=request
        )

    if phone >= CAPS.per_phone:
        with pytest.raises(DomainError) as err:
            run()
        assert err.value.code == "GUEST_PHONE_LIMIT"
        assert err.value.details["limit"] == 2
    elif request and doctor_day >= CAPS.pending_per_doctor_day:
        with pytest.raises(DomainError) as err:
            run()
        assert err.value.code == "ONLINE_DOCTOR_DAY_FULL"
    else:
        run()


def test_the_whatsapp_link_carries_the_status_and_reference_never_a_pin() -> None:
    facts = g.BookingFacts(
        center_ar="مركز النيل",
        center_en="Nile Center",
        doctor_ar="د. سارة",
        doctor_en="Dr Sara",
        when="2026-11-02 09:30",
        status="awaiting_approval",
        reference="ABCDE-FGH23",
    )
    text = g.status_message(facts)
    assert "Nile Center" in text
    assert "مركز النيل" in text
    assert "ABCDE-FGH23" in text
    assert "waiting for reception" in text
    url = g.whatsapp_url("0912 345 678", text)
    assert url is not None
    assert url.startswith("https://wa.me/249912345678?text=")
    assert unquote(url.split("?text=", 1)[1]) == text
    assert g.whatsapp_url("not a phone", text) is None
    share = g.share_url(g.share_message(center_ar="", center_en="Nile", reference="X", page=""))
    assert share.startswith("https://wa.me/?text=")
