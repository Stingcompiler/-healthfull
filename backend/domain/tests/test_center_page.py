"""The public center page: opening hours, today's status, announcements, contact links."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.center_page import (
    DayHours,
    announcement_visible,
    parse_hours,
    tel_uri,
    today_status,
    validate_announcement_dates,
    whatsapp_number,
)
from domain.errors import DomainError


def _code(fn, *args) -> str:
    with pytest.raises(DomainError) as exc:
        fn(*args)
    return exc.value.code


def _week(**overrides: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {"weekday": d, "closed": False, "opens": "08:00", "closes": "16:00"} for d in range(7)
    ]
    for key, value in overrides.items():
        rows[int(key[1:])] = value
    return rows


# --- hours --------------------------------------------------------------------------------


def test_empty_hours_mean_not_published() -> None:
    assert parse_hours([]) == []


def test_full_week_parses_in_weekday_order() -> None:
    rows = list(reversed(_week(d4={"weekday": 4, "closed": True, "opens": None, "closes": None})))
    days = parse_hours(rows)
    assert [d.weekday for d in days] == list(range(7))
    assert days[4] == DayHours(weekday=4, closed=True, opens=None, closes=None)
    assert days[0].opens == time(8, 0)
    assert days[0].closes == time(16, 0)


def test_closed_day_drops_its_times() -> None:
    days = parse_hours(
        _week(d5={"weekday": 5, "closed": True, "opens": "08:00", "closes": "09:00"})
    )
    assert days[5].opens is None
    assert days[5].closes is None


@pytest.mark.parametrize(
    "rows",
    [
        _week()[:6],  # a weekday missing
        [*_week()[:6], {"weekday": 0, "closed": True}],  # a weekday twice
        _week(d0={"weekday": 7, "closed": True}),  # out of range
        _week(d1={"weekday": 1, "closed": False, "opens": "16:00", "closes": "08:00"}),
        _week(d1={"weekday": 1, "closed": False, "opens": "08:00", "closes": "08:00"}),
        _week(d1={"weekday": 1, "closed": False, "opens": "8am", "closes": "16:00"}),
        _week(d1={"weekday": 1, "closed": False, "opens": None, "closes": "16:00"}),
        _week(d1={"weekday": 1, "closed": False, "opens": "25:00", "closes": "26:00"}),
        _week(d1="monday"),  # type: ignore[arg-type]
        _week(d1={"weekday": True, "closed": False, "opens": "08:00", "closes": "09:00"}),
    ],
)
def test_bad_hours_are_refused(rows: list[dict[str, object]]) -> None:
    assert _code(parse_hours, rows) == "CENTER_HOURS_INVALID"


_hm = st.tuples(st.integers(0, 23), st.integers(0, 59)).map(lambda hm: time(*hm))


@given(opens=_hm, closes=_hm, weekday=st.integers(0, 6), now=_hm)
def test_today_status_is_consistent(opens: time, closes: time, weekday: int, now: time) -> None:
    rows = _week()
    rows[weekday] = {
        "weekday": weekday,
        "closed": False,
        "opens": f"{opens:%H:%M}",
        "closes": f"{closes:%H:%M}",
    }
    if closes <= opens:
        assert _code(parse_hours, rows) == "CENTER_HOURS_INVALID"
        return
    days = parse_hours(rows)
    # 2026-10-19 is a Monday (weekday 0).
    moment = datetime.combine(date(2026, 10, 19) + timedelta(days=weekday), now)
    status = today_status(days, moment)
    assert status is not None
    assert status.weekday == weekday
    assert (status.opens, status.closes) == (opens, closes)
    if now < opens:
        assert status.state == "opens_later"
    elif now < closes:
        assert status.state == "open"
    else:
        assert status.state == "closed_now"


def test_today_closed_and_unpublished() -> None:
    days = parse_hours(_week(d4={"weekday": 4, "closed": True}))
    friday = datetime(2026, 10, 23, 10, 0)  # weekday 4
    status = today_status(days, friday)
    assert status is not None
    assert status.state == "closed_today"
    assert today_status([], friday) is None


# --- announcements ------------------------------------------------------------------------

_day = st.dates(min_value=date(2026, 1, 1), max_value=date(2027, 12, 31))


@given(
    active=st.booleans(),
    starts=st.none() | _day,
    ends=st.none() | _day,
    today=_day,
)
def test_announcement_visible_only_when_active_and_in_range(
    active: bool, starts: date | None, ends: date | None, today: date
) -> None:
    shown = announcement_visible(active=active, starts_on=starts, ends_on=ends, today=today)
    expected = active and (starts is None or starts <= today) and (ends is None or today <= ends)
    assert shown is expected


def test_announcement_dates_must_be_ordered() -> None:
    validate_announcement_dates(date(2026, 10, 1), date(2026, 10, 1))
    validate_announcement_dates(None, date(2026, 10, 1))
    validate_announcement_dates(date(2026, 10, 1), None)
    assert (
        _code(validate_announcement_dates, date(2026, 10, 2), date(2026, 10, 1))
        == "ANNOUNCEMENT_DATES_INVALID"
    )


# --- contact links ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "digits"),
    [
        ("0912345678", "249912345678"),
        ("0912 345 678", "249912345678"),
        ("+249 912-345-678", "249912345678"),
        ("00249912345678", "249912345678"),
        ("912345678", "249912345678"),
        ("٠٩١٢٣٤٥٦٧٨", "249912345678"),
        ("+971 50 123 4567", "971501234567"),
        ("", ""),
    ],
)
def test_whatsapp_number_is_international_digits(typed: str, digits: str) -> None:
    assert whatsapp_number(typed) == digits


@pytest.mark.parametrize("typed", ["12", "abc", "+249 9123456789012345", "0912345678x"])
def test_bad_whatsapp_number_is_refused(typed: str) -> None:
    assert _code(whatsapp_number, typed) == "CENTER_WHATSAPP_INVALID"


@given(st.text(max_size=40))
def test_tel_uri_keeps_only_a_plus_and_digits(raw: str) -> None:
    uri = tel_uri(raw)
    if uri:
        body = uri.removeprefix("tel:")
        assert body.lstrip("+").isascii()
        assert body.lstrip("+").isdigit()
        assert "+" not in body[1:]


def test_tel_uri_examples() -> None:
    assert tel_uri("0183 123 456") == "tel:0183123456"
    assert tel_uri("+249 183 123456") == "tel:+249183123456"
    assert tel_uri("—") == ""
