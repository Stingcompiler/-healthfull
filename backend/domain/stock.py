"""Stock: units, FEFO batch selection and the append-only move ledger (ARCHITECTURE 4.8).

* Quantities are whole base units (e.g. tablets). ``UnitConversion("box", "strip", 3)``
  means one box holds three strips; factors compose down to the base unit.
* On-hand of ``(item, batch, store)`` is the sum of its signed stock moves. Stock never goes
  negative: every batch of moves is checked as a whole before it is stored (services do
  this under ``SELECT ... FOR UPDATE`` on the batch rows).
* Stock decrements at dispense (invariant 5); invoicing never creates moves.
* FEFO: dispense picks non-empty, usable batches by earliest expiry (batches without an
  expiry last, then by batch id). A batch is usable while ``expiry >= today +
  min_days_left`` (default 0: usable through its expiry date). A pharmacist may choose other
  batches with a reason; expired batches are never dispensed.
* A stock count turns each difference between book and counted quantity into a
  ``count_correction`` move.

Error codes: ``INVALID_QUANTITY``, ``INVALID_CONVERSION``, ``UNIT_UNKNOWN``,
``STOCK_INSUFFICIENT``, ``BATCH_UNKNOWN``, ``BATCH_EXPIRED``, ``DUPLICATE_BATCH``,
``OVERRIDE_QUANTITY_MISMATCH``, ``MOVE_SIGN_INVALID``, ``TRANSFER_SAME_STORE``,
``REASON_REQUIRED``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from domain.audit import Approval
from domain.errors import DomainError

__all__ = [
    "BatchStock",
    "CountLine",
    "MoveKind",
    "Pick",
    "StockKey",
    "StockMoveDraft",
    "UnitConversion",
    "adjustment_move",
    "apply_moves",
    "count_adjustments",
    "dispense_moves",
    "expiring_within",
    "fefo_order",
    "from_base",
    "is_low_stock",
    "is_usable",
    "on_hand",
    "select_batches",
    "to_base",
    "transfer_moves",
    "unit_factors",
    "validate_move",
]

#: ``(item_id, batch_id, store_id)``
type StockKey = tuple[int, int, int]


def _count(value: int, name: str = "quantity", *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DomainError(
            "INVALID_QUANTITY", f"{name} must be a whole number >= {minimum}", **{name: value}
        )
    return value


# --- units ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UnitConversion:
    """One ``from_unit`` holds ``factor`` of ``to_unit``."""

    from_unit: str
    to_unit: str
    factor: int


def unit_factors(base_unit: str, conversions: Iterable[UnitConversion]) -> dict[str, int]:
    """Base units per unit, e.g. ``{"tablet": 1, "strip": 10, "box": 30}``."""
    convs = list(conversions)
    defined: dict[str, UnitConversion] = {}
    for c in convs:
        if isinstance(c.factor, bool) or not isinstance(c.factor, int) or c.factor < 1:
            raise DomainError(
                "INVALID_CONVERSION", "Factors are whole numbers >= 1", unit=c.from_unit
            )
        if c.from_unit == base_unit or c.from_unit in defined or c.from_unit == c.to_unit:
            raise DomainError("INVALID_CONVERSION", "Each unit is defined once", unit=c.from_unit)
        defined[c.from_unit] = c
    factors = {base_unit: 1}
    progress = True
    while progress:
        progress = False
        for unit, c in defined.items():
            if unit not in factors and c.to_unit in factors:
                factors[unit] = c.factor * factors[c.to_unit]
                progress = True
    unresolved = sorted(set(defined) - set(factors))
    if unresolved:
        raise DomainError(
            "INVALID_CONVERSION", "Some units never reach the base unit", units=unresolved
        )
    return factors


def _factor(unit: str, factors: Mapping[str, int]) -> int:
    try:
        return factors[unit]
    except KeyError:
        raise DomainError("UNIT_UNKNOWN", "Unknown unit for this item", unit=unit) from None


def to_base(quantity: int, unit: str, factors: Mapping[str, int]) -> int:
    return _count(quantity, minimum=0) * _factor(unit, factors)


def from_base(base_quantity: int, unit: str, factors: Mapping[str, int]) -> tuple[int, int]:
    """``(whole units, remaining base units)``."""
    return divmod(_count(base_quantity, minimum=0), _factor(unit, factors))


# --- batches and FEFO ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BatchStock:
    batch_id: int
    expiry: date | None
    on_hand: int


@dataclass(frozen=True, slots=True)
class Pick:
    batch_id: int
    quantity: int


def is_usable(expiry: date | None, today: date, min_days_left: int = 0) -> bool:
    """Not expired (usable through the expiry date) with ``min_days_left`` to spare."""
    return expiry is None or expiry >= today + timedelta(days=min_days_left)


def fefo_order(
    batches: Iterable[BatchStock], today: date, min_days_left: int = 0
) -> list[BatchStock]:
    """Usable batches with stock, earliest expiry first (no expiry last, then batch id)."""
    usable = [b for b in batches if b.on_hand > 0 and is_usable(b.expiry, today, min_days_left)]
    return sorted(usable, key=lambda b: (b.expiry is None, b.expiry or date.max, b.batch_id))


def select_batches(
    batches: Sequence[BatchStock],
    quantity: int,
    today: date,
    *,
    min_days_left: int = 0,
    override: Sequence[Pick] | None = None,
    approval: Approval | None = None,
) -> tuple[Pick, ...]:
    """Batches to dispense ``quantity`` base units from.

    Without ``override`` this is the FEFO suggestion. An ``override`` that differs from it
    needs an :class:`Approval` (the pharmacist's reason).
    """
    qty = _count(quantity)
    ordered = fefo_order(batches, today, min_days_left)
    available = sum(b.on_hand for b in ordered)
    suggestion: tuple[Pick, ...] | None = None
    if qty <= available:
        picks: list[Pick] = []
        left = qty
        for b in ordered:
            if left == 0:
                break
            take = min(b.on_hand, left)
            picks.append(Pick(b.batch_id, take))
            left -= take
        suggestion = tuple(picks)
    if override is None:
        if suggestion is None:
            raise DomainError(
                "STOCK_INSUFFICIENT", "Not enough usable stock", needed=qty, available=available
            )
        return suggestion

    by_id = {b.batch_id: b for b in batches}
    seen: set[int] = set()
    for p in override:
        _count(p.quantity)
        if p.batch_id in seen:
            raise DomainError("DUPLICATE_BATCH", "A batch appears twice", batch_id=p.batch_id)
        seen.add(p.batch_id)
        batch = by_id.get(p.batch_id)
        if batch is None:
            raise DomainError("BATCH_UNKNOWN", "Unknown batch", batch_id=p.batch_id)
        if not is_usable(batch.expiry, today):
            raise DomainError(
                "BATCH_EXPIRED", "Expired batches are never dispensed", batch_id=p.batch_id
            )
        if p.quantity > batch.on_hand:
            raise DomainError(
                "STOCK_INSUFFICIENT",
                "Not enough stock in the chosen batch",
                batch_id=p.batch_id,
                needed=p.quantity,
                available=batch.on_hand,
            )
    total = sum(p.quantity for p in override)
    if total != qty:
        raise DomainError(
            "OVERRIDE_QUANTITY_MISMATCH",
            "Chosen batches must add up to the quantity",
            needed=qty,
            chosen=total,
        )
    chosen = tuple(override)
    if chosen != suggestion and approval is None:
        raise DomainError("REASON_REQUIRED", "Choosing other batches than FEFO needs a reason")
    return chosen


# --- moves --------------------------------------------------------------------------------------


class MoveKind(StrEnum):
    RECEIPT = "receipt"
    DISPENSE = "dispense"
    ADJUSTMENT = "adjustment"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"
    COUNT_CORRECTION = "count_correction"
    RETURN = "return"


_POSITIVE = frozenset({MoveKind.RECEIPT, MoveKind.TRANSFER_IN})
_NEGATIVE = frozenset({MoveKind.DISPENSE, MoveKind.TRANSFER_OUT})


def validate_move(kind: MoveKind, quantity: int) -> None:
    """Receipts and transfers in add; dispenses and transfers out remove; others either way."""
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity == 0:
        raise DomainError("MOVE_SIGN_INVALID", "A stock move is a non-zero whole number")
    if (kind in _POSITIVE and quantity < 0) or (kind in _NEGATIVE and quantity > 0):
        raise DomainError(
            "MOVE_SIGN_INVALID",
            "Wrong sign for this kind of move",
            kind=str(kind),
            quantity=quantity,
        )


@dataclass(frozen=True, slots=True)
class StockMoveDraft:
    item_id: int
    batch_id: int
    store_id: int
    quantity: int
    kind: MoveKind

    def __post_init__(self) -> None:
        validate_move(self.kind, self.quantity)

    @property
    def key(self) -> StockKey:
        return (self.item_id, self.batch_id, self.store_id)


def on_hand(moves: Iterable[StockMoveDraft]) -> dict[StockKey, int]:
    out: dict[StockKey, int] = defaultdict(int)
    for m in moves:
        out[m.key] += m.quantity
    return dict(out)


def apply_moves(
    current: Mapping[StockKey, int], moves: Iterable[StockMoveDraft]
) -> dict[StockKey, int]:
    """New on-hand after ``moves``; refuses the whole set if any key would go negative."""
    after = dict(current)
    for m in moves:
        after[m.key] = after.get(m.key, 0) + m.quantity
    short = {k: v for k, v in after.items() if v < 0}
    if short:
        key = min(short)
        raise DomainError(
            "STOCK_INSUFFICIENT",
            "Stock cannot go negative",
            item_id=key[0],
            batch_id=key[1],
            store_id=key[2],
            available=current.get(key, 0),
            shortfall=-short[key],
        )
    return after


def adjustment_move(
    item_id: int,
    batch_id: int,
    store_id: int,
    quantity: int,
    *,
    available: int,
    approval: Approval,
) -> StockMoveDraft:
    """A manual adjustment (damage, expiry, found stock) with an approver and a reason.

    FEATURES 8.6: the reason is recorded and a supervisor approves. The batch's on-hand
    (``available``) must stay non-negative.
    """
    if not isinstance(approval, Approval):
        raise TypeError("adjustment_move() needs an Approval")
    move = StockMoveDraft(item_id, batch_id, store_id, quantity, MoveKind.ADJUSTMENT)
    if available + quantity < 0:
        raise DomainError(
            "STOCK_INSUFFICIENT",
            "Stock cannot go negative",
            batch_id=batch_id,
            available=available,
            shortfall=-(available + quantity),
        )
    return move


def dispense_moves(
    item_id: int, store_id: int, picks: Iterable[Pick]
) -> tuple[StockMoveDraft, ...]:
    return tuple(
        StockMoveDraft(item_id, p.batch_id, store_id, -_count(p.quantity), MoveKind.DISPENSE)
        for p in picks
    )


def transfer_moves(
    item_id: int, batch_id: int, *, from_store: int, to_store: int, quantity: int, available: int
) -> tuple[StockMoveDraft, StockMoveDraft]:
    """A transfer between stores: one move out, one move in, summing to zero."""
    qty = _count(quantity)
    if from_store == to_store:
        raise DomainError("TRANSFER_SAME_STORE", "Source and destination stores must differ")
    if qty > available:
        raise DomainError(
            "STOCK_INSUFFICIENT", "Not enough stock to transfer", needed=qty, available=available
        )
    return (
        StockMoveDraft(item_id, batch_id, from_store, -qty, MoveKind.TRANSFER_OUT),
        StockMoveDraft(item_id, batch_id, to_store, qty, MoveKind.TRANSFER_IN),
    )


# --- counts and reports ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CountLine:
    item_id: int
    batch_id: int
    store_id: int
    book_qty: int
    counted_qty: int

    def __post_init__(self) -> None:
        _count(self.counted_qty, "counted_qty", minimum=0)
        _count(self.book_qty, "book_qty", minimum=0)

    @property
    def variance(self) -> int:
        """``counted - book`` (negative = missing stock)."""
        return self.counted_qty - self.book_qty


def count_adjustments(lines: Iterable[CountLine]) -> tuple[StockMoveDraft, ...]:
    return tuple(
        StockMoveDraft(ln.item_id, ln.batch_id, ln.store_id, ln.variance, MoveKind.COUNT_CORRECTION)
        for ln in lines
        if ln.variance != 0
    )


def is_low_stock(on_hand_total: int, min_stock: int) -> bool:
    """At or below the item's minimum: time to reorder (FEATURES 8.9)."""
    return on_hand_total <= min_stock


def expiring_within(batches: Iterable[BatchStock], today: date, days: int) -> list[BatchStock]:
    """Batches with stock that expire within ``days`` (already expired included), soonest first."""
    limit = today + timedelta(days=days)
    hits = [b for b in batches if b.on_hand > 0 and b.expiry is not None and b.expiry <= limit]
    return sorted(hits, key=lambda b: (b.expiry or date.max, b.batch_id))
