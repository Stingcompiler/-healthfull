"""Offline proof-of-work of public booking requests (ADR 0029 F)."""

from __future__ import annotations

import hashlib

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from domain import proof_of_work as pow_
from domain.errors import DomainError

KEY = b"test-key"
NOW = 1_800_000_000
_ids = st.from_regex(r"[0-9a-f]{16}", fullmatch=True)


@given(st.binary(min_size=1, max_size=40))
def test_leading_zero_bits_matches_the_integer_reading(digest: bytes) -> None:
    value = int.from_bytes(digest, "big")
    expected = len(digest) * 8 - value.bit_length()
    assert pow_.leading_zero_bits(digest) == expected


@settings(max_examples=40)
@given(_ids, st.integers(min_value=0, max_value=8))
def test_a_solved_challenge_verifies_once_its_signature_holds(cid: str, bits: int) -> None:
    challenge = pow_.issue(KEY, challenge_id=cid, expires=NOW + 300, bits=bits)
    nonce = pow_.solve(challenge.token, bits)
    got = pow_.verify(KEY, challenge.token, nonce, now=NOW, min_bits=bits)
    assert (got.id, got.bits) == (cid, bits)
    digest = hashlib.sha256((challenge.token + nonce).encode()).digest()
    assert pow_.leading_zero_bits(digest) >= bits


def _code(token: str, nonce: str, *, now: int = NOW, min_bits: int = 0, key: bytes = KEY) -> str:
    with pytest.raises(DomainError) as err:
        pow_.verify(key, token, nonce, now=now, min_bits=min_bits)
    return err.value.code


def test_forged_weakened_expired_or_unsolved_challenges_are_refused() -> None:
    challenge = pow_.issue(KEY, challenge_id="0123456789abcdef", expires=NOW + 300, bits=8)
    nonce = pow_.solve(challenge.token, 8)
    # Another key, an edited difficulty, an edited expiry: the signature fails.
    assert _code(challenge.token, nonce, key=b"other") == "POW_INVALID"
    cid, expires, _, mac = challenge.token.split(".")
    assert _code(f"{cid}.{expires}.0.{mac}", "1") == "POW_INVALID"
    assert _code(f"{cid}.{int(expires) + 999}.8.{mac}", nonce) == "POW_INVALID"
    # Weaker than the difficulty in force now.
    assert _code(challenge.token, nonce, min_bits=9) == "POW_INVALID"
    # Expired.
    assert _code(challenge.token, nonce, now=NOW + 300) == "POW_EXPIRED"
    # A nonce that does not solve it (find one).
    bad = next(str(n) for n in range(10_000) if not pow_.solves(challenge.token, str(n), 8))
    assert _code(challenge.token, bad) == "POW_INVALID"
    # Malformed input.
    for token, n in (("", "1"), ("a.b.c", "1"), (challenge.token, ""), (challenge.token, "x" * 65)):
        assert _code(token, n) == "POW_INVALID"


@given(st.text(max_size=80), st.text(max_size=70))
def test_verify_never_crashes_on_garbage(token: str, nonce: str) -> None:
    with pytest.raises(DomainError) as err:
        pow_.verify(KEY, token, nonce, now=NOW, min_bits=0)
    assert err.value.code in {"POW_INVALID", "POW_EXPIRED"}


def test_issue_checks_its_inputs() -> None:
    with pytest.raises(ValueError, match="challenge_id"):
        pow_.issue(KEY, challenge_id="XYZ", expires=NOW, bits=1)
    with pytest.raises(ValueError, match="bits"):
        pow_.issue(KEY, challenge_id="0123456789abcdef", expires=NOW, bits=33)
