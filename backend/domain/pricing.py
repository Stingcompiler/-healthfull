"""Price lists with effective dates (FEATURES 5.2, 5.4; invariant 6).

A price list (cash, or one per payer) has dated versions. Each version is a complete
snapshot of item prices. The version that prices a line is the one with the latest
``effective_from`` on or before the invoice approval date; the price is then frozen on the
invoice line.

A bulk percentage update produces the prices of a new version: every (or a chosen subset
of) price is scaled by ``1 + percent/100`` and rounded to a step (e.g. the nearest 5 SDG).

Error codes: ``NO_EFFECTIVE_PRICE_LIST``, ``PRICE_NOT_FOUND``, ``INVALID_PRICE``,
``INVALID_PERCENT``, ``INVALID_ROUNDING_STEP``, ``PRICE_VERSION_BACKDATED``,
``PRICE_VERSION_DATE_TAKEN``.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, localcontext
from enum import StrEnum
from types import MappingProxyType

from domain.errors import DomainError
from domain.money import CENT, HUNDRED, is_money, q

__all__ = [
    "MAX_INCREASE_PERCENT",
    "ItemKey",
    "PriceVersion",
    "RoundMode",
    "RoundingRule",
    "bulk_percentage_update",
    "effective_version",
    "round_price",
    "unit_price",
    "validate_new_version",
]

type ItemKey = int | str

#: Upper bound of a bulk increase; a typo such as 1500 instead of 15 is refused.
MAX_INCREASE_PERCENT = Decimal(1000)


class RoundMode(StrEnum):
    HALF_UP = "half_up"
    UP = "up"
    DOWN = "down"


_ROUNDING = {
    RoundMode.HALF_UP: ROUND_HALF_UP,
    RoundMode.UP: ROUND_CEILING,
    RoundMode.DOWN: ROUND_FLOOR,
}


@dataclass(frozen=True, slots=True)
class RoundingRule:
    """Round to a multiple of ``step`` (money, > 0) using ``mode``."""

    step: Decimal = CENT
    mode: RoundMode = RoundMode.HALF_UP

    def __post_init__(self) -> None:
        if not is_money(self.step) or self.step <= 0:
            raise DomainError(
                "INVALID_ROUNDING_STEP",
                "Rounding step must be a positive amount with at most 2 decimals",
                step=str(self.step),
            )


def round_price(amount: Decimal, rule: RoundingRule) -> Decimal:
    """Round a non-negative amount (any precision) to the rule's step."""
    if not isinstance(amount, Decimal) or not amount.is_finite() or amount < 0:
        raise DomainError("INVALID_PRICE", "Price must be a non-negative number", value=str(amount))
    with localcontext() as ctx:
        ctx.prec = 60
        units = (amount / rule.step).to_integral_value(rounding=_ROUNDING[rule.mode])
        return q(units * rule.step)


def _check_price(key: object, price: Decimal) -> Decimal:
    if not is_money(price) or price < 0:
        raise DomainError(
            "INVALID_PRICE",
            "Prices must be non-negative amounts with at most 2 decimals",
            item=str(key),
            value=str(price),
        )
    return q(price)


def _frozen_prices(prices: Mapping[ItemKey, Decimal]) -> Mapping[ItemKey, Decimal]:
    return MappingProxyType({key: _check_price(key, price) for key, price in prices.items()})


@dataclass(frozen=True, slots=True)
class PriceVersion:
    """One dated, complete snapshot of a price list."""

    version_id: int
    effective_from: date
    prices: Mapping[ItemKey, Decimal] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "prices", _frozen_prices(self.prices))


def effective_version(versions: Iterable[PriceVersion], on: date) -> PriceVersion:
    """The version with the latest ``effective_from <= on`` (ties: highest ``version_id``).

    Raises:
        DomainError: ``NO_EFFECTIVE_PRICE_LIST`` if no version has started by ``on``.
    """
    started = [v for v in versions if v.effective_from <= on]
    if not started:
        raise DomainError(
            "NO_EFFECTIVE_PRICE_LIST", "No price list version is effective", on=on.isoformat()
        )
    return max(started, key=lambda v: (v.effective_from, v.version_id))


def unit_price(versions: Iterable[PriceVersion], item: ItemKey, on: date) -> Decimal:
    """Price of ``item`` in the version effective on ``on`` (``PRICE_NOT_FOUND`` if absent)."""
    version = effective_version(versions, on)
    try:
        return version.prices[item]
    except KeyError:
        raise DomainError(
            "PRICE_NOT_FOUND",
            "The item has no price in the effective price list",
            item=item,
            version_id=version.version_id,
        ) from None


def validate_new_version(
    existing: Iterable[PriceVersion], effective_from: date, today: date
) -> None:
    """A new version starts tomorrow or later, on a date no other version uses.

    Backdating is refused: it would change which version was effective on days whose
    invoices are already frozen. A version starting today is refused too while another
    version is already effective today: invoices approved earlier today froze that version's
    prices, and two prices would then claim to be "the list effective that day" (invariant
    6). Only the first version of a list that has nothing effective yet may start today (no
    invoice can have been priced from it).
    """
    versions = list(existing)
    started = [v for v in versions if v.effective_from <= today]
    if effective_from < today or (effective_from == today and started):
        raise DomainError(
            "PRICE_VERSION_BACKDATED",
            "A new price list version starts tomorrow at the earliest",
            effective_from=effective_from.isoformat(),
        )
    if any(v.effective_from == effective_from for v in versions):
        raise DomainError(
            "PRICE_VERSION_DATE_TAKEN",
            "Another version of this price list starts on that date",
            effective_from=effective_from.isoformat(),
        )


def bulk_percentage_update[K: (int, str)](
    prices: Mapping[K, Decimal],
    percent: Decimal | int,
    rule: RoundingRule | None = None,
    *,
    only: Collection[K] | None = None,
) -> dict[K, Decimal]:
    """Prices for a new version: each price times ``(100 + percent) / 100``, rounded.

    ``percent`` may be negative (a decrease) but must be greater than -100 and at most
    :data:`MAX_INCREASE_PERCENT`. With ``only``, the other prices are copied unchanged.
    """
    if isinstance(percent, bool) or not isinstance(percent, Decimal | int):
        raise TypeError("percent must be Decimal or int")
    p = Decimal(percent)
    if not p.is_finite() or p <= -HUNDRED or p > MAX_INCREASE_PERCENT:
        raise DomainError(
            "INVALID_PERCENT",
            "Percent must be greater than -100 and at most 1000",
            percent=str(p),
        )
    chosen = set(prices) if only is None else set(only)
    missing = chosen - set(prices)
    if missing:
        raise DomainError(
            "PRICE_NOT_FOUND", "Some items are not on this price list", items=sorted(missing)
        )
    rounding = rule or RoundingRule()
    for key, old in prices.items():
        _check_price(key, old)
    out: dict[K, Decimal] = {}
    with localcontext() as ctx:
        ctx.prec = 60
        for key, old in prices.items():
            if key in chosen:
                out[key] = round_price(old * (HUNDRED + p) / HUNDRED, rounding)
            else:
                out[key] = old
    return out
