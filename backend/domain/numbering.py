"""Document numbers such as ``INV-2026-000123`` (FEATURES 13.6).

Numbers restart at 1 every calendar year per prefix. The counter itself lives in the
``core.Sequence`` table (locked with ``SELECT ... FOR UPDATE``); this module only formats
and parses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from domain.errors import DomainError

__all__ = ["DEFAULT_WIDTH", "DocumentNumber", "format_document_number", "parse_document_number"]

DEFAULT_WIDTH = 6
_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]{0,9}$")
_NUMBER_RE = re.compile(r"^(?P<prefix>[A-Z][A-Z0-9]{0,9})-(?P<year>\d{4})-(?P<seq>\d+)$")


@dataclass(frozen=True, slots=True)
class DocumentNumber:
    prefix: str
    year: int
    seq: int


def _validate(prefix: str, year: int, seq: int, width: int) -> None:
    if not _PREFIX_RE.match(prefix):
        raise DomainError(
            "INVALID_SEQUENCE_PREFIX",
            "Prefix must be 1-10 upper-case letters/digits starting with a letter",
            prefix=prefix,
        )
    if not 1000 <= year <= 9999:
        raise DomainError("INVALID_SEQUENCE_YEAR", "Year must have 4 digits", year=year)
    if seq < 1:
        raise DomainError("INVALID_SEQUENCE_NUMBER", "Sequence numbers start at 1", seq=seq)
    if not 1 <= width <= 12:
        raise DomainError("INVALID_SEQUENCE_WIDTH", "Width must be between 1 and 12", width=width)


def format_document_number(prefix: str, year: int, seq: int, width: int = DEFAULT_WIDTH) -> str:
    """Format ``("INV", 2026, 123)`` as ``"INV-2026-000123"``.

    Numbers wider than ``width`` are never truncated.
    """
    _validate(prefix, year, seq, width)
    return f"{prefix}-{year:04d}-{seq:0{width}d}"


def parse_document_number(text: str) -> DocumentNumber:
    """Inverse of :func:`format_document_number`."""
    m = _NUMBER_RE.match(text)
    if not m:
        raise DomainError("INVALID_DOCUMENT_NUMBER", "Malformed document number", value=text)
    number = DocumentNumber(prefix=m["prefix"], year=int(m["year"]), seq=int(m["seq"]))
    _validate(number.prefix, number.year, number.seq, DEFAULT_WIDTH)
    return number
