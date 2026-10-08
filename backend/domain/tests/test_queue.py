"""Queue rules without a database: who is called next, and the waiting-room name format."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.queue import (
    QueueCandidate,
    abbreviate_name,
    next_to_call,
    serving_key,
    tokens_ahead,
)

STATUSES = ("waiting", "called", "in_progress", "done", "no_show", "cancelled")

candidates = st.lists(
    st.builds(
        QueueCandidate,
        entry_id=st.integers(1, 10_000),
        token_no=st.integers(1, 500),
        priority=st.sampled_from([0, 0, 0, 10]),
        status=st.sampled_from(STATUSES),
        ready=st.booleans(),
    ),
    max_size=30,
    unique_by=lambda c: c.entry_id,
)


# --- next_to_call ---------------------------------------------------------------------------


@given(candidates)
def test_next_to_call_is_the_first_waiting_ready_entry(entries: list[QueueCandidate]) -> None:
    chosen = next_to_call(entries)
    callable_ = [e for e in entries if e.status == "waiting" and e.ready]
    if not callable_:
        assert chosen is None
        return
    assert chosen is not None
    assert chosen.status == "waiting"
    assert chosen.ready
    assert all(serving_key(chosen) <= serving_key(e) for e in callable_)


@given(candidates)
def test_next_to_call_ignores_input_order(entries: list[QueueCandidate]) -> None:
    assert next_to_call(entries) == next_to_call(list(reversed(entries)))


def test_emergency_priority_comes_before_lower_tokens() -> None:
    entries = [
        QueueCandidate(1, token_no=1, priority=0, status="waiting", ready=True),
        QueueCandidate(2, token_no=7, priority=10, status="waiting", ready=True),
        QueueCandidate(3, token_no=2, priority=0, status="waiting", ready=False),
    ]
    chosen = next_to_call(entries)
    assert chosen is not None
    assert chosen.entry_id == 2


def test_unpaid_and_called_entries_are_never_called_next() -> None:
    entries = [
        QueueCandidate(1, token_no=1, priority=0, status="called", ready=True),
        QueueCandidate(2, token_no=2, priority=0, status="waiting", ready=False),
    ]
    assert next_to_call(entries) is None


@given(candidates, st.integers(1, 10_000))
def test_tokens_ahead_counts_waiting_entries_served_first(
    entries: list[QueueCandidate], probe: int
) -> None:
    target = next((e for e in entries if e.entry_id == probe), None)
    if target is None:
        assert tokens_ahead(entries, probe) == 0
        return
    expected = sum(
        1
        for e in entries
        if e.entry_id != probe
        and e.status in ("waiting", "called")
        and serving_key(e) < serving_key(target)
    )
    assert tokens_ahead(entries, probe) == expected


# --- abbreviate_name ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "short"),
    [
        ("أحمد محمد علي", "أحمد م."),
        ("Ahmed Mohamed Ali", "Ahmed M."),
        ("عبد الله الطيب حسن", "عبد الله ط."),
        ("abd alrahman osman", "abd alrahman O."),
        ("فاطمة", "فاطمة"),
        ("  سارة   عبد الرحيم  ", "سارة ع."),
        ("د. أحمد الطيب", "أحمد ط."),
        ("Dr. Salma Awad", "Salma A."),
        ("محمد ال", "محمد ا."),
        ("", ""),
        ("   ", ""),
        ("— 123", ""),
    ],
)
def test_abbreviate_name_examples(name: str, short: str) -> None:
    assert abbreviate_name(name) == short


arabic_words = st.text(alphabet="ابتثجحخدذرزسشصضطظعغفقكلمنهوي", min_size=2, max_size=8)
latin_words = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=2, max_size=8)


@given(st.lists(arabic_words | latin_words, min_size=3, max_size=5))
def test_abbreviation_never_shows_the_family_names(words: list[str]) -> None:
    """Only the first name and one initial reach a public screen (privacy, FEATURES 2.3)."""
    name = " ".join(words)
    short = abbreviate_name(name)
    parts = short.split(" ")
    initial = parts[-1]
    assert initial.endswith(".")
    assert len(initial) == 2
    shown = parts[:-1]
    # The shown words are the leading words of the name; later words never appear whole.
    assert shown == words[: len(shown)]
    assert len(shown) <= 2
    for later in words[len(shown) + 1 :]:
        if later not in shown:
            assert later not in parts


@given(st.lists(arabic_words | latin_words, min_size=1, max_size=5))
def test_abbreviation_is_never_longer_than_the_name(words: list[str]) -> None:
    name = " ".join(words)
    short = abbreviate_name(name)
    assert short
    assert len(short) <= len(name) + 1  # the added "."
    assert abbreviate_name(name) == short  # deterministic
