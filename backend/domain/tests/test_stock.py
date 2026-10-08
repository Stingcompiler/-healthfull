from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.audit import Approval
from domain.errors import DomainError
from domain.stock import (
    BatchStock,
    CountLine,
    MoveKind,
    Pick,
    StockMoveDraft,
    UnitConversion,
    adjustment_move,
    apply_moves,
    count_adjustments,
    dispense_moves,
    expiring_within,
    from_base,
    is_low_stock,
    is_usable,
    on_hand,
    select_batches,
    to_base,
    transfer_moves,
    unit_factors,
    validate_move,
)

TODAY = date(2026, 10, 7)
OK = Approval(approver_id=2, at=datetime(2026, 10, 7, tzinfo=UTC), reason="patient asked")
LADDER = [UnitConversion("box", "strip", 3), UnitConversion("strip", "tablet", 10)]


# --- units -------------------------------------------------------------------------------


def test_unit_factors_compose_to_base_units() -> None:
    f = unit_factors("tablet", LADDER)
    assert f == {"tablet": 1, "strip": 10, "box": 30}
    assert to_base(2, "box", f) == 60
    assert from_base(65, "box", f) == (2, 5)


@given(st.integers(0, 10_000), st.sampled_from(["tablet", "strip", "box"]))
def test_from_base_round_trips(qty: int, unit: str) -> None:
    f = unit_factors("tablet", LADDER)
    whole, rest = from_base(qty, unit, f)
    assert to_base(whole, unit, f) + rest == qty
    assert 0 <= rest < f[unit]


@pytest.mark.parametrize(
    "conversions",
    [
        [UnitConversion("box", "strip", 0)],
        [UnitConversion("box", "strip", 10)],  # strip never reaches the base unit
        [UnitConversion("box", "tablet", 10), UnitConversion("box", "tablet", 20)],
        [UnitConversion("a", "b", 2), UnitConversion("b", "a", 2)],
    ],
)
def test_invalid_conversions(conversions: list[UnitConversion]) -> None:
    with pytest.raises(DomainError) as exc:
        unit_factors("tablet", conversions)
    assert exc.value.code == "INVALID_CONVERSION"


def test_unknown_unit() -> None:
    with pytest.raises(DomainError) as exc:
        to_base(1, "bottle", unit_factors("tablet", LADDER))
    assert exc.value.code == "UNIT_UNKNOWN"


# --- FEFO ----------------------------------------------------------------------------------


@st.composite
def batches(draw: st.DrawFn) -> list[BatchStock]:
    n = draw(st.integers(0, 6))
    return [
        BatchStock(
            batch_id=i + 1,
            expiry=draw(
                st.none() | st.dates(TODAY - timedelta(days=30), TODAY + timedelta(days=400))
            ),
            on_hand=draw(st.integers(0, 50)),
        )
        for i in range(n)
    ]


def _usable(bs: list[BatchStock]) -> list[BatchStock]:
    return [b for b in bs if b.on_hand > 0 and is_usable(b.expiry, TODAY)]


@given(batches(), st.integers(1, 120))
def test_fefo_selection(stock: list[BatchStock], qty: int) -> None:
    available = sum(b.on_hand for b in _usable(stock))
    if qty > available:
        with pytest.raises(DomainError) as exc:
            select_batches(stock, qty, TODAY)
        assert exc.value.code == "STOCK_INSUFFICIENT"
        assert exc.value.details["available"] == available
        return
    picks = select_batches(stock, qty, TODAY)
    by_id = {b.batch_id: b for b in stock}
    assert sum(p.quantity for p in picks) == qty
    assert all(p.quantity > 0 for p in picks)
    for p in picks:
        b = by_id[p.batch_id]
        assert p.quantity <= b.on_hand
        assert is_usable(b.expiry, TODAY)
    # Earliest expiry first (no expiry last): every usable batch that expires strictly
    # before a picked one is used up completely.
    picked = {p.batch_id: p.quantity for p in picks}
    far = date.max
    for p in picks:
        exp = by_id[p.batch_id].expiry or far
        for b in _usable(stock):
            if (b.expiry or far) < exp:
                assert picked.get(b.batch_id) == b.on_hand


def test_fefo_skips_expired_and_empty_batches() -> None:
    stock = [
        BatchStock(1, TODAY - timedelta(days=1), 100),  # expired
        BatchStock(2, TODAY + timedelta(days=10), 0),  # empty
        BatchStock(3, TODAY + timedelta(days=90), 5),
        BatchStock(4, TODAY, 3),  # expires today: still usable, so first
        BatchStock(5, None, 50),
    ]
    assert select_batches(stock, 10, TODAY) == (Pick(4, 3), Pick(3, 5), Pick(5, 2))
    # A center policy can demand a minimum shelf life left at dispense.
    assert select_batches(stock, 2, TODAY, min_days_left=30) == (Pick(3, 2),)


def test_override_needs_a_reason_and_valid_batches() -> None:
    stock = [
        BatchStock(1, TODAY + timedelta(days=5), 10),
        BatchStock(2, TODAY + timedelta(days=50), 10),
    ]
    chosen = (Pick(2, 4),)
    assert select_batches(stock, 4, TODAY, override=chosen, approval=OK) == chosen
    with pytest.raises(DomainError) as exc:
        select_batches(stock, 4, TODAY, override=chosen)
    assert exc.value.code == "REASON_REQUIRED"
    # Choosing exactly the FEFO suggestion needs no reason.
    assert select_batches(stock, 4, TODAY, override=(Pick(1, 4),)) == (Pick(1, 4),)
    cases = [
        ((Pick(2, 3),), "OVERRIDE_QUANTITY_MISMATCH"),
        ((Pick(2, 11),), "STOCK_INSUFFICIENT"),
        ((Pick(9, 4),), "BATCH_UNKNOWN"),
        ((Pick(2, 2), Pick(2, 2)), "DUPLICATE_BATCH"),
        ((Pick(2, 0), Pick(1, 4)), "INVALID_QUANTITY"),
    ]
    for override, code in cases:
        with pytest.raises(DomainError) as exc:
            select_batches(stock, 4, TODAY, override=override, approval=OK)
        assert exc.value.code == code
    expired = [BatchStock(1, TODAY - timedelta(days=1), 10)]
    with pytest.raises(DomainError) as exc:
        select_batches(expired, 1, TODAY, override=(Pick(1, 1),), approval=OK)
    assert exc.value.code == "BATCH_EXPIRED"


# --- moves and on-hand (invariant 5) --------------------------------------------------------------


def test_move_signs() -> None:
    for kind in (MoveKind.RECEIPT, MoveKind.TRANSFER_IN):
        validate_move(kind, 1)
        with pytest.raises(DomainError) as exc:
            validate_move(kind, -1)
        assert exc.value.code == "MOVE_SIGN_INVALID"
    for kind in (MoveKind.DISPENSE, MoveKind.TRANSFER_OUT):
        validate_move(kind, -1)
        with pytest.raises(DomainError):
            validate_move(kind, 1)
    for kind in (MoveKind.ADJUSTMENT, MoveKind.COUNT_CORRECTION, MoveKind.RETURN):
        validate_move(kind, 1)
        validate_move(kind, -1)
    for kind in MoveKind:
        with pytest.raises(DomainError):
            validate_move(kind, 0)


moves_st = st.lists(
    st.builds(
        StockMoveDraft,
        item_id=st.just(1),
        batch_id=st.integers(1, 3),
        store_id=st.integers(1, 2),
        quantity=st.integers(-20, 20).filter(lambda x: x != 0),
        kind=st.sampled_from([MoveKind.ADJUSTMENT, MoveKind.RETURN]),
    ),
    max_size=30,
)


@given(moves_st)
def test_apply_moves_never_goes_negative(moves: list[StockMoveDraft]) -> None:
    state: dict[tuple[int, int, int], int] = {}
    accepted: list[StockMoveDraft] = []
    refused: set[str] = set()
    for m in moves:
        try:
            state = apply_moves(state, [m])
        except DomainError as exc:
            refused.add(exc.code)
            continue
        accepted.append(m)
        assert all(v >= 0 for v in state.values())
    assert state == on_hand(accepted)
    assert refused <= {"STOCK_INSUFFICIENT"}


def test_apply_moves_is_all_or_nothing() -> None:
    state = {(1, 1, 1): 5}
    moves = [
        StockMoveDraft(1, 1, 1, -3, MoveKind.DISPENSE),
        StockMoveDraft(1, 1, 1, -3, MoveKind.DISPENSE),
    ]
    with pytest.raises(DomainError) as exc:
        apply_moves(state, moves)
    assert exc.value.code == "STOCK_INSUFFICIENT"
    assert state == {(1, 1, 1): 5}


def test_dispense_and_transfer_moves() -> None:
    picks = (Pick(4, 3), Pick(3, 5))
    moves = dispense_moves(item_id=9, store_id=1, picks=picks)
    assert moves == (
        StockMoveDraft(9, 4, 1, -3, MoveKind.DISPENSE),
        StockMoveDraft(9, 3, 1, -5, MoveKind.DISPENSE),
    )
    out, into = transfer_moves(9, 4, from_store=1, to_store=2, quantity=2, available=3)
    assert (out.quantity, into.quantity, out.store_id, into.store_id) == (-2, 2, 1, 2)
    with pytest.raises(DomainError) as exc:
        transfer_moves(9, 4, from_store=1, to_store=2, quantity=4, available=3)
    assert exc.value.code == "STOCK_INSUFFICIENT"
    with pytest.raises(DomainError) as exc:
        transfer_moves(9, 4, from_store=1, to_store=1, quantity=1, available=3)
    assert exc.value.code == "TRANSFER_SAME_STORE"


# --- counts -------------------------------------------------------------------------------------


@given(st.lists(st.tuples(st.integers(0, 100), st.integers(0, 100)), max_size=10))
def test_count_adjustments_bring_book_to_counted(pairs: list[tuple[int, int]]) -> None:
    lines = [CountLine(1, i + 1, 1, book, counted) for i, (book, counted) in enumerate(pairs)]
    moves = count_adjustments(lines)
    state = {(1, ln.batch_id, 1): ln.book_qty for ln in lines}
    after = apply_moves(state, moves)
    for ln in lines:
        assert after[(1, ln.batch_id, 1)] == ln.counted_qty
    assert all(m.kind is MoveKind.COUNT_CORRECTION and m.quantity != 0 for m in moves)


def test_count_cannot_be_negative() -> None:
    with pytest.raises(DomainError) as exc:
        CountLine(1, 1, 1, 5, -1)
    assert exc.value.code == "INVALID_QUANTITY"


# --- reports -------------------------------------------------------------------------------------


def test_low_stock_and_expiry_window() -> None:
    assert is_low_stock(4, 5)
    assert is_low_stock(5, 5)
    assert not is_low_stock(6, 5)
    stock = [
        BatchStock(1, TODAY + timedelta(days=10), 1),
        BatchStock(2, TODAY + timedelta(days=45), 1),
        BatchStock(3, None, 1),
        BatchStock(4, TODAY + timedelta(days=10), 0),
        BatchStock(5, TODAY - timedelta(days=1), 2),
    ]
    assert [b.batch_id for b in expiring_within(stock, TODAY, 30)] == [5, 1]
    assert [b.batch_id for b in expiring_within(stock, TODAY, 60)] == [5, 1, 2]


# --- adjustments (FEATURES 8.6) -------------------------------------------------------------


def test_adjustment_needs_approval_and_never_goes_negative() -> None:
    move = adjustment_move(1, 2, 1, -3, available=5, approval=OK)
    assert (move.quantity, move.kind) == (-3, MoveKind.ADJUSTMENT)
    assert adjustment_move(1, 2, 1, 4, available=0, approval=OK).quantity == 4
    with pytest.raises(DomainError) as exc:
        adjustment_move(1, 2, 1, -6, available=5, approval=OK)
    assert exc.value.code == "STOCK_INSUFFICIENT"
    with pytest.raises(DomainError) as exc:
        adjustment_move(1, 2, 1, 0, available=5, approval=OK)
    assert exc.value.code == "MOVE_SIGN_INVALID"
    with pytest.raises(TypeError):
        adjustment_move(1, 2, 1, -1, available=5, approval=None)  # type: ignore[arg-type]
