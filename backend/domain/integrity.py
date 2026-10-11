"""Comparisons behind ``manage.py integrity_check`` (pure; no Django).

The integrity check reads two views of the same money or stock, one derived from the business
documents and one from the ledger (or the stock balance table), and reports every key where
they differ. A key missing on one side counts as zero there, so a ledger balance with no
document (or a document with no posting) is found too.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

ZERO = Decimal("0")

#: Problems listed per check; the count is always complete.
MAX_LISTED = 20


@dataclass(frozen=True, slots=True)
class Mismatch[K: Hashable]:
    key: K
    expected: Decimal
    actual: Decimal

    @property
    def difference(self) -> Decimal:
        return self.actual - self.expected


def compare_amounts[K: Hashable](
    expected: Mapping[K, Decimal], actual: Mapping[K, Decimal]
) -> list[Mismatch[K]]:
    """Every key where ``actual`` differs from ``expected`` (a missing key is zero),
    ordered by the key's text so reports are stable."""
    keys = set(expected) | set(actual)
    out = [
        Mismatch(k, expected.get(k, ZERO), actual.get(k, ZERO))
        for k in keys
        if expected.get(k, ZERO) != actual.get(k, ZERO)
    ]
    return sorted(out, key=lambda m: str(m.key))


@dataclass(slots=True)
class CheckResult:
    """One named check: ``problems`` lists at most :data:`MAX_LISTED` lines, ``count`` is the
    full number found, ``checked`` how many rows or keys were looked at."""

    name: str
    checked: int = 0
    count: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.count == 0

    def add(self, problem: str) -> None:
        self.count += 1
        if len(self.problems) < MAX_LISTED:
            self.problems.append(problem)

    def add_all(self, problems: Iterable[str]) -> None:
        for p in problems:
            self.add(p)


def all_ok(results: Iterable[CheckResult]) -> bool:
    return all(r.ok for r in results)
