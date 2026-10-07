from __future__ import annotations

import pytest

from domain.errors import DomainError


def test_domain_error_carries_code_message_and_details() -> None:
    err = DomainError("INVOICE_FROZEN", "Invoice is approved", invoice_id=7)
    assert err.code == "INVOICE_FROZEN"
    assert err.message == "Invoice is approved"
    assert err.details == {"invoice_id": 7}
    assert str(err) == "Invoice is approved"
    assert err.as_dict() == {
        "code": "INVOICE_FROZEN",
        "message": "Invoice is approved",
        "details": {"invoice_id": 7},
    }
    assert "INVOICE_FROZEN" in repr(err)


def test_message_defaults_to_code() -> None:
    err = DomainError("SHIFT_NOT_OPEN")
    assert err.message == "SHIFT_NOT_OPEN"
    assert err.details == {}


def test_as_dict_returns_a_copy() -> None:
    err = DomainError("X_Y", a=1)
    d = err.as_dict()
    d["details"]["a"] = 2
    assert err.details == {"a": 1}


@pytest.mark.parametrize("bad", ["", "lower", "Has Space", "1LEADING_DIGIT", "DASH-ED"])
def test_code_must_be_upper_snake_case(bad: str) -> None:
    with pytest.raises(ValueError, match="UPPER_SNAKE_CASE"):
        DomainError(bad)
