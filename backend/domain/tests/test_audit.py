from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain.audit import Approval, require_reason
from domain.errors import DomainError
from domain.money import require_money, require_non_negative, require_positive

AT = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)

blank = st.text(alphabet=" \t\n 　", max_size=5)


@given(blank)
def test_blank_reason_is_refused(text: str) -> None:
    with pytest.raises(DomainError) as exc:
        require_reason(text)
    assert exc.value.code == "REASON_REQUIRED"


@given(st.text(min_size=1).filter(lambda s: s.strip() != ""))
def test_any_visible_reason_is_kept_stripped(text: str) -> None:
    assert require_reason(text) == text.strip()


def test_reason_code_alone_is_enough() -> None:
    assert require_reason(None, "PATIENT_REFUSED") == ""
    assert require_reason("  ", "PATIENT_REFUSED") == ""
    with pytest.raises(DomainError):
        require_reason(None, "  ")


def test_approval_records_who_when_why() -> None:
    a = Approval(approver_id=7, at=AT, reason="  patient refused  ")
    assert a.approver_id == 7
    assert a.at == AT
    assert a.reason_text == "patient refused"


@pytest.mark.parametrize("approver", [0, -1, True])
def test_approval_needs_a_real_approver(approver: int) -> None:
    with pytest.raises(DomainError) as exc:
        Approval(approver_id=approver, at=AT, reason="x")
    assert exc.value.code == "APPROVER_REQUIRED"


def test_approval_needs_an_aware_time() -> None:
    with pytest.raises(DomainError) as exc:
        Approval(approver_id=1, at=datetime(2026, 10, 7, 9, 0), reason="x")
    assert exc.value.code == "INVALID_TIMESTAMP"


def test_approval_needs_a_reason() -> None:
    with pytest.raises(DomainError) as exc:
        Approval(approver_id=1, at=AT, reason=" ")
    assert exc.value.code == "REASON_REQUIRED"
    assert Approval(approver_id=1, at=AT, reason_code="DAMAGED").reason_code == "DAMAGED"


# --- money validators ----------------------------------------------------------------


@given(st.decimals(min_value=-1000, max_value=1000, places=2))
def test_require_money_accepts_two_places(x: Decimal) -> None:
    assert require_money(x) == x


@pytest.mark.parametrize("bad", [Decimal("1.001"), Decimal("NaN")])
def test_require_money_refuses_other_values(bad: Decimal) -> None:
    with pytest.raises(DomainError) as exc:
        require_money(bad, "price")
    assert exc.value.code == "INVALID_AMOUNT"
    assert exc.value.details["field"] == "price"


def test_require_money_refuses_non_decimals() -> None:
    with pytest.raises(TypeError):
        require_money(1.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        require_money(1)  # type: ignore[arg-type]


@given(st.decimals(min_value=-1000, max_value=1000, places=2))
def test_sign_validators(x: Decimal) -> None:
    if x >= 0:
        assert require_non_negative(x) == x
    else:
        with pytest.raises(DomainError) as exc:
            require_non_negative(x, "discount")
        assert exc.value.code == "INVALID_AMOUNT"
        assert exc.value.details["field"] == "discount"
    if x > 0:
        assert require_positive(x) == x
    else:
        with pytest.raises(DomainError):
            require_positive(x)
