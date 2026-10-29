"""Public site switches and settings (ADR 0028, 0029): guards, seeding, booking rules."""

from __future__ import annotations

from datetime import timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.errors import DomainError
from domain.public_site import (
    LEGACY_ENV,
    RULE_DEFAULTS,
    RULE_RANGES,
    Switches,
    booking_rules,
    clamp,
    initial_values,
    require_online_booking,
    require_site,
    require_tracking,
    tracking_turned_off,
)

switches = st.builds(Switches, st.booleans(), st.booleans(), st.booleans())

GUARDS = [
    (require_site, "site", "SITE_DISABLED"),
    (require_online_booking, "online_booking", "ONLINE_BOOKING_DISABLED"),
    (require_tracking, "patient_tracking", "PORTAL_DISABLED"),
]


@pytest.mark.parametrize(("guard", "field", "code"), GUARDS)
@given(s=switches)
def test_a_guard_refuses_exactly_when_its_own_switch_is_off(
    guard: object, field: str, code: str, s: Switches
) -> None:
    if getattr(s, field):
        guard(s)  # type: ignore[operator]
        return
    with pytest.raises(DomainError) as err:
        guard(s)  # type: ignore[operator]
    assert err.value.code == code


@given(before=switches, after=switches)
def test_sessions_end_only_when_tracking_goes_from_on_to_off(
    before: Switches, after: Switches
) -> None:
    assert tracking_turned_off(before, after) == (
        before.patient_tracking and not after.patient_tracking
    )


def test_defaults_are_inside_their_ranges_and_cover_the_same_names() -> None:
    assert set(RULE_DEFAULTS) == set(RULE_RANGES)
    for name, value in RULE_DEFAULTS.items():
        low, high = RULE_RANGES[name]
        assert low <= value <= high, name
    assert set(LEGACY_ENV) <= set(RULE_RANGES)


def test_the_owner_accepted_defaults() -> None:
    assert RULE_DEFAULTS["max_pending_per_doctor_day"] == 10
    assert RULE_DEFAULTS["max_requests_per_address_day"] == 5
    assert RULE_DEFAULTS["pow_difficulty_bits"] == 18
    assert RULE_DEFAULTS["guest_retention_days"] == 90
    assert RULE_DEFAULTS["min_review_minutes"] == 30
    assert RULE_DEFAULTS["request_ttl_hours"] == 24
    assert RULE_DEFAULTS["max_guest_bookings_per_phone"] == 2


def test_new_install_starts_with_everything_off_and_approval_on() -> None:
    values = initial_values(existing_install=False, env={})
    assert values["site_enabled"] is False
    assert values["online_booking_enabled"] is False
    assert values["patient_tracking_enabled"] is False
    assert values["require_approval"] is True


def test_existing_install_keeps_portal_and_instant_booking_but_not_the_website() -> None:
    values = initial_values(existing_install=True, env={})
    assert values["site_enabled"] is False
    assert values["online_booking_enabled"] is True
    assert values["patient_tracking_enabled"] is True
    assert values["require_approval"] is False


def test_legacy_environment_values_become_the_first_values() -> None:
    env = {
        "PORTAL_BOOKING_LEAD_MINUTES": "90",
        "PORTAL_BOOKING_HORIZON_DAYS": "14",
        "PORTAL_MAX_OPEN_APPOINTMENTS": "5",
        "PORTAL_CANCEL_CUTOFF_HOURS": "6",
    }
    values = initial_values(existing_install=True, env=env)
    assert (values["lead_minutes"], values["horizon_days"]) == (90, 14)
    assert (values["max_open"], values["cancel_cutoff_hours"]) == (5, 6)


@given(
    existing=st.booleans(),
    raw=st.dictionaries(
        st.sampled_from(sorted(LEGACY_ENV.values())),
        st.one_of(st.integers(-(10**6), 10**6).map(str), st.text(max_size=5)),
    ),
)
def test_seeding_never_writes_a_value_out_of_range(existing: bool, raw: dict[str, str]) -> None:
    values = initial_values(existing_install=existing, env=raw)
    for name, (low, high) in RULE_RANGES.items():
        assert low <= values[name] <= high, name


@given(name=st.sampled_from(sorted(RULE_RANGES)), value=st.integers(-(10**9), 10**9))
def test_clamp_is_inside_and_identity_inside(name: str, value: int) -> None:
    low, high = RULE_RANGES[name]
    result = clamp(name, value)
    assert low <= result <= high
    if low <= value <= high:
        assert result == value


@given(
    lead=st.integers(*RULE_RANGES["lead_minutes"]),
    horizon=st.integers(*RULE_RANGES["horizon_days"]),
    max_open=st.integers(*RULE_RANGES["max_open"]),
    cutoff=st.integers(*RULE_RANGES["cancel_cutoff_hours"]),
)
def test_every_value_in_range_makes_valid_booking_rules(
    lead: int, horizon: int, max_open: int, cutoff: int
) -> None:
    rules = booking_rules(
        lead_minutes=lead, horizon_days=horizon, max_open=max_open, cancel_cutoff_hours=cutoff
    )
    assert rules.lead == timedelta(minutes=lead)
    assert rules.horizon_days == horizon
    assert rules.max_open == max_open
    assert rules.cancel_cutoff == timedelta(hours=cutoff)


def test_offered_rules_leave_the_review_window() -> None:
    from datetime import timedelta

    from domain.public_site import booking_rules, offered_booking_rules, request_rules

    base = booking_rules(lead_minutes=60, horizon_days=30, max_open=3, cancel_cutoff_hours=2)
    on = request_rules(require_approval=True, request_ttl_hours=24, min_review_minutes=30)
    off = request_rules(require_approval=False, request_ttl_hours=24, min_review_minutes=30)
    assert offered_booking_rules(base, off) == base
    widened = offered_booking_rules(base, on)
    assert widened.lead == timedelta(minutes=90)
    assert widened.cancel_cutoff == base.cancel_cutoff
