"""Doctor queue rules that need no database (FEATURES 2.3, 2.6).

* Serving order: higher priority first (emergencies), then the lower token number.
* Call next: the first entry in serving order that is waiting and ready. Ready means the
  consultation fee is settled or covered by a perform-first authorization, or none is due
  (invariant 1); an unpaid visit keeps its token but is never called.
* Tokens ahead (printed on the token slip): ready entries still waiting or called that are
  served before this one.
* Waiting-room screens show a name only as the first name and the initial of the next
  name ("Ahmed M.", "عبد الله ط."): enough for a patient to recognise the call, never the
  family names (privacy).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

__all__ = [
    "QueueCandidate",
    "abbreviate_name",
    "next_to_call",
    "serving_key",
    "tokens_ahead",
]

#: Queue statuses still in front of a later token (they will reach the doctor first).
_AHEAD_STATUSES = frozenset({"waiting", "called"})

#: First words that form one name with the next word (عبد الله, أبو بكر, Abd Alrahman).
_COMPOUND_PREFIXES = frozenset({"عبد", "ابو", "أبو", "abd", "abu"})
_ARTICLE = "ال"


@dataclass(frozen=True, slots=True)
class QueueCandidate:
    """One queue entry as the rules see it."""

    entry_id: int
    token_no: int
    priority: int
    status: str
    ready: bool


def serving_key(entry: QueueCandidate) -> tuple[int, int, int]:
    """Sort key of the serving order: priority (high first), token, then id for ties."""
    return (-entry.priority, entry.token_no, entry.entry_id)


def next_to_call(entries: Iterable[QueueCandidate]) -> QueueCandidate | None:
    """The waiting, ready entry served first, or ``None`` when nobody can be called."""
    callable_ = [e for e in entries if e.status == "waiting" and e.ready]
    return min(callable_, key=serving_key, default=None)


def tokens_ahead(entries: Iterable[QueueCandidate], entry_id: int) -> int:
    """How many ready waiting or called entries are served before ``entry_id`` (0 if unknown).

    Entries that are not ready (consultation fee unpaid) are skipped by :func:`next_to_call`,
    so they are not ahead of anyone.
    """
    items = list(entries)
    target = next((e for e in items if e.entry_id == entry_id), None)
    if target is None:
        return 0
    key = serving_key(target)
    return sum(
        1
        for e in items
        if e.entry_id != entry_id
        and e.ready
        and e.status in _AHEAD_STATUSES
        and serving_key(e) < key
    )


def _is_title(word: str) -> bool:
    """A title or abbreviation such as "د." or "Dr.", never part of the name."""
    return word.endswith(".") and len(word) <= 5


def _has_letter(word: str) -> bool:
    return any(ch.isalpha() for ch in word)


def _initial(word: str) -> str:
    """First letter of a name word, skipping the Arabic article (الطيب -> ط)."""
    letters = [ch for ch in word if ch.isalpha()]
    if len(letters) > 3 and letters[0] + letters[1] == _ARTICLE:
        letters = letters[2:]
    return letters[0].upper() if letters else ""


def abbreviate_name(full_name: str) -> str:
    """The first name and the initial of the next name, for public screens.

    A compound first name (عبد الله, Abu Bakr) stays whole; titles are dropped; a single
    name is shown as it is. Returns ``""`` when the text holds no name.
    """
    words = [w for w in full_name.split() if _has_letter(w) and not _is_title(w)]
    if not words:
        return ""
    take = 2 if len(words) > 1 and words[0].lower() in _COMPOUND_PREFIXES else 1
    first, rest = words[:take], words[take:]
    if not rest:
        return " ".join(first)
    initial = _initial(rest[0])
    return f"{' '.join(first)} {initial}." if initial else " ".join(first)
