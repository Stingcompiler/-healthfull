"""Money arithmetic.

Rules (ARCHITECTURE 4.3):

* Money is ``decimal.Decimal`` with exactly 2 places, rounded ``ROUND_HALF_UP``.
  Floats are rejected outright, never converted.
* Any split computes one side and derives the other by subtraction, so parts always
  sum exactly to the whole. Multi-way splits use the largest-remainder method in
  whole cents, which has the same guarantee.

Every function here is property-tested in ``domain/tests/test_money.py``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

from domain.errors import DomainError

__all__ = [
    "CENT",
    "HUNDRED",
    "MAX_AMOUNT",
    "ZERO",
    "MoneyInput",
    "allocate",
    "is_money",
    "money",
    "percent_of",
    "q",
    "split_even",
    "split_percent",
    "sum_money",
]

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
HUNDRED = Decimal("100")
#: Largest amount that fits ``DecimalField(max_digits=14, decimal_places=2)``.
MAX_AMOUNT = Decimal("999999999999.99")

# Generous precision so quantize never fails on legitimately large intermediate values.
_PRECISION = 60

type MoneyInput = Decimal | int | str

#: ASCII-only: ``[0-9]`` and re.ASCII, because a bare ``\d`` matches any Unicode digit.
_MONEY_TEXT = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?", re.ASCII)

#: Arabic-Indic (U+0660..) and extended Arabic-Indic (U+06F0..) digits are accepted and
#: normalised, since Sudanese users type both; so is the Arabic decimal separator U+066B.
#: The Arabic thousands separator U+066C is not mapped, so it is rejected like ",".
_ARABIC_DIGITS = str.maketrans(
    {
        **{chr(0x0660 + i): str(i) for i in range(10)},
        **{chr(0x06F0 + i): str(i) for i in range(10)},
        "\u066b": ".",
    }
)


def _invalid(value: object, reason: str) -> DomainError:
    return DomainError("INVALID_AMOUNT", f"Invalid money amount {value!r}: {reason}")


def q(value: Decimal) -> Decimal:
    """Quantize a Decimal to 2 places using ROUND_HALF_UP.

    Raises:
        TypeError: if ``value`` is not a Decimal (floats are never accepted).
        DomainError: ``INVALID_AMOUNT`` if the value is NaN or infinite.
    """
    if not isinstance(value, Decimal):
        raise TypeError(f"q() expects Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise _invalid(value, "not a finite number")
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        try:
            result = value.quantize(CENT, rounding=ROUND_HALF_UP)
        except InvalidOperation as exc:  # pragma: no cover - guarded by precision
            raise _invalid(value, "out of range") from exc
    # Normalise negative zero so ``str(q(Decimal("-0.001")))`` is "0.00".
    return ZERO if result == 0 else result


def money(value: MoneyInput) -> Decimal:
    """Build a money Decimal (2 places, ROUND_HALF_UP) from Decimal, int or str.

    Raises:
        TypeError: for floats, bools or any other type.
        DomainError: ``INVALID_AMOUNT`` for strings that are not plain positional decimals
            (separators, underscores, exponents, NaN/infinity) and for non-finite Decimals.
    """
    if isinstance(value, bool) or not isinstance(value, Decimal | int | str):
        raise TypeError(f"money() does not accept {type(value).__name__}")
    if isinstance(value, Decimal):
        return q(value)
    if isinstance(value, int):
        return q(Decimal(value))
    text = value.strip().translate(_ARABIC_DIGITS)
    # Strict positional notation only. Decimal() alone would also accept "1_5" (PEP 515
    # underscores, giving 15), "1e3", "NaN" and ".5"; separators are refused on purpose so
    # "1,5" or "1 000" can never silently become another amount.
    if not _MONEY_TEXT.fullmatch(text):
        raise _invalid(value, "expected digits with an optional sign and decimal point")
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - the pattern admits only valid input
        raise _invalid(value, "not a number") from exc
    return q(parsed)


def is_money(value: object) -> bool:
    """True if ``value`` is a finite Decimal with at most 2 decimal places."""
    if not isinstance(value, Decimal) or not value.is_finite():
        return False
    return q(value) == value


def _require_money(value: Decimal, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")
    if not is_money(value):
        raise _invalid(value, f"{name} must be finite with at most 2 decimal places")
    return q(value)


def _require_percent(percent: Decimal | int) -> Decimal:
    if isinstance(percent, bool) or not isinstance(percent, Decimal | int):
        raise TypeError(f"percent must be Decimal or int, got {type(percent).__name__}")
    p = Decimal(percent)
    if not p.is_finite() or p < 0 or p > HUNDRED:
        raise DomainError(
            "INVALID_PERCENT", f"Percent must be between 0 and 100, got {percent}", percent=str(p)
        )
    return p


def percent_of(amount: Decimal, percent: Decimal | int) -> Decimal:
    """``amount * percent / 100`` rounded to money. ``percent`` must be in [0, 100]."""
    amt = _require_money(amount, "amount")
    p = _require_percent(percent)
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        return q(amt * p / HUNDRED)


def split_percent(total: Decimal, percent: Decimal | int) -> tuple[Decimal, Decimal]:
    """Split ``total`` into ``(part, rest)`` where ``part`` is ``percent`` of it.

    ``rest`` is derived by subtraction, so ``part + rest == total`` exactly.
    For ``total >= 0`` both parts are in ``[0, total]``.
    """
    whole = _require_money(total, "total")
    part = percent_of(whole, percent)
    return part, whole - part


def allocate(total: Decimal, weights: Sequence[Decimal | int]) -> list[Decimal]:
    """Split ``total`` across ``weights`` proportionally, exact to the cent.

    Uses the largest-remainder method in whole cents: each part gets the floor of its
    exact share, then leftover cents go to the largest fractional remainders (ties
    broken by position, so the result is deterministic). Guarantees:

    * ``sum(parts) == total`` exactly and ``len(parts) == len(weights)``;
    * every part is within one cent of its exact proportional share;
    * a zero weight receives zero; parts share the sign of ``total``.

    Raises:
        DomainError: ``INVALID_WEIGHTS`` if weights are empty, negative, non-finite, or
            all zero while ``total`` is non-zero.
    """
    whole = _require_money(total, "total")
    if not weights:
        raise DomainError("INVALID_WEIGHTS", "At least one weight is required")
    ws: list[Decimal] = []
    for w in weights:
        if isinstance(w, bool) or not isinstance(w, Decimal | int):
            raise TypeError(f"weights must be Decimal or int, got {type(w).__name__}")
        d = Decimal(w)
        if not d.is_finite() or d < 0:
            raise DomainError("INVALID_WEIGHTS", f"Weights must be finite and >= 0, got {w}")
        ws.append(d)
    weight_sum = sum(ws, Decimal(0))
    if weight_sum == 0:
        if whole == 0:
            return [ZERO for _ in ws]
        raise DomainError("INVALID_WEIGHTS", "Cannot allocate a non-zero total over zero weights")

    sign = -1 if whole < 0 else 1
    total_cents = int(abs(whole) * 100)
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        exact = [Decimal(total_cents) * w / weight_sum for w in ws]
        floors = [int(e.to_integral_value(rounding=ROUND_FLOOR)) for e in exact]
        remainders = [e - f for e, f in zip(exact, floors, strict=True)]
    leftover = total_cents - sum(floors)
    order = sorted(range(len(ws)), key=lambda i: (-remainders[i], i))
    for i in order[:leftover]:
        floors[i] += 1
    return [q(Decimal(sign * cents) / 100) for cents in floors]


def split_even(total: Decimal, parts: int) -> list[Decimal]:
    """Split ``total`` into ``parts`` near-equal amounts summing exactly to ``total``.

    Earlier parts receive the extra cents; parts differ by at most one cent.
    """
    if isinstance(parts, bool) or not isinstance(parts, int) or parts < 1:
        raise DomainError("INVALID_WEIGHTS", f"parts must be a positive int, got {parts!r}")
    return allocate(total, [1] * parts)


def sum_money(values: Iterable[Decimal]) -> Decimal:
    """Sum money values exactly; every value must already be money (2 places)."""
    total = ZERO
    for v in values:
        total += _require_money(v, "value")
    return q(total)
