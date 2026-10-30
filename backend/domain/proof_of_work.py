"""Offline proof-of-work for public booking requests (ADR 0029 F). Pure: no Django.

No CAPTCHA service exists on a LAN or offline, so the booking form asks the server for a
**challenge** (signed, expiring, single use) and the browser finds a **nonce** such that
``SHA-256(challenge + nonce)`` starts with ``bits`` zero bits. The server checks the signature
in constant time, the expiry, that the difficulty is at least the one in force, and the hash.
Single use is the service's job (it records the challenge id).

Honest limit (ADR 0029 F): it slows a scripted flood; it does not stop a determined attacker.
The caps, reception review and expiry are the real defense.

A challenge is ``<id>.<expires>.<bits>.<mac>``: ``id`` 16 hex characters, ``expires`` Unix
seconds, ``bits`` the difficulty, ``mac`` 32 hex characters of HMAC-SHA256 over the rest.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass

from domain.errors import DomainError

__all__ = [
    "MAX_BITS",
    "Challenge",
    "issue",
    "leading_zero_bits",
    "solve",
    "solves",
    "verify",
]

MAX_BITS = 32
_ID = re.compile(r"^[0-9a-f]{16}$")
_NONCE = re.compile(r"^[0-9A-Za-z]{1,64}$")
_DOMAIN = b"hospital.portal.pow:"


@dataclass(frozen=True, slots=True)
class Challenge:
    id: str
    expires: int  # Unix seconds
    bits: int
    token: str


def _mac(key: bytes, body: str) -> str:
    return hmac.new(key, _DOMAIN + body.encode(), hashlib.sha256).hexdigest()[:32]


def issue(key: bytes, *, challenge_id: str, expires: int, bits: int) -> Challenge:
    """A signed challenge. ``challenge_id``: 16 hex characters from ``secrets.token_hex(8)``."""
    if not _ID.match(challenge_id):
        raise ValueError("challenge_id must be 16 lowercase hex characters")
    if not 0 <= bits <= MAX_BITS:
        raise ValueError("bits out of range")
    body = f"{challenge_id}.{expires}.{bits}"
    return Challenge(challenge_id, expires, bits, f"{body}.{_mac(key, body)}")


def leading_zero_bits(digest: bytes) -> int:
    """How many leading bits of ``digest`` are zero."""
    count = 0
    for byte in digest:
        if byte == 0:
            count += 8
            continue
        return count + 8 - byte.bit_length()
    return count


def solves(token: str, nonce: str, bits: int) -> bool:
    """Whether ``SHA-256(token + nonce)`` starts with ``bits`` zero bits."""
    digest = hashlib.sha256((token + nonce).encode()).digest()
    return leading_zero_bits(digest) >= bits


def solve(token: str, bits: int, *, start: int = 0) -> str:
    """The first decimal nonce from ``start`` that solves ``token`` (tests and tooling; the
    browser runs the same search in a worker)."""
    nonce = start
    while not solves(token, str(nonce), bits):
        nonce += 1
    return str(nonce)


def _invalid() -> DomainError:
    return DomainError("POW_INVALID", "The form check did not pass; reload the page and try again")


def verify(key: bytes, token: str, nonce: str, *, now: int, min_bits: int) -> Challenge:
    """Check a solved challenge.

    Raises:
        DomainError: ``POW_INVALID`` (malformed, forged, weaker than ``min_bits`` or not
            solved), ``POW_EXPIRED``.
    """
    parts = (token or "").split(".")
    if len(parts) != 4 or not _ID.match(parts[0]) or not _NONCE.match(nonce or ""):
        raise _invalid()
    challenge_id, expires_text, bits_text, mac = parts
    if not (expires_text.isascii() and expires_text.isdigit()):
        raise _invalid()
    if not (bits_text.isascii() and bits_text.isdigit()):
        raise _invalid()
    body = f"{challenge_id}.{expires_text}.{bits_text}"
    if not hmac.compare_digest(_mac(key, body).encode(), mac.encode()):
        raise _invalid()
    expires, bits = int(expires_text), int(bits_text)
    if expires <= now:
        raise DomainError("POW_EXPIRED", "The form waited too long; try again")
    if bits < min_bits or bits > MAX_BITS or not solves(token, nonce, bits):
        raise _invalid()
    return Challenge(challenge_id, expires, bits, token)
