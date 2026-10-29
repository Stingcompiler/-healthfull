"""Website content of the public center page (ADR 0029 H, plan section 3, Phase 2).

Fixed sections, not a CMS: short bilingual rows with size caps, a plain maps link, and the rule
that an edited testimonial needs a new approval. Nothing here knows about prices: the website
never shows them (ADR 0023, 0029 A5).

Error codes: ``CENTER_ROWS_INVALID`` (facilities or reasons), ``CENTER_MAPS_URL_INVALID``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from domain.errors import DomainError

__all__ = [
    "FACILITIES_MAX",
    "FACILITY_NAME_MAX",
    "FACILITY_ROW",
    "MAPS_URL_MAX",
    "REASONS_MAX",
    "REASON_ROW",
    "REASON_TEXT_MAX",
    "REASON_TITLE_MAX",
    "RowSpec",
    "approval_lapses_on_edit",
    "maps_link",
    "parse_rows",
]

FACILITIES_MAX = 20
FACILITY_NAME_MAX = 80
REASONS_MAX = 8
REASON_TITLE_MAX = 80
REASON_TEXT_MAX = 200
MAPS_URL_MAX = 500

_SPACE = re.compile(r"\s")


@dataclass(frozen=True, slots=True)
class RowSpec:
    """The shape of one row: its bilingual title fields (one of the pair is required) and the
    optional bilingual text fields, each with its maximum length; at most ``max_rows`` rows."""

    label: str
    max_rows: int
    title: tuple[str, str]
    title_max: int
    text: tuple[str, str] | None = None
    text_max: int = 0

    @property
    def keys(self) -> tuple[str, ...]:
        return self.title + (self.text or ())


FACILITY_ROW = RowSpec("facilities", FACILITIES_MAX, ("name_ar", "name_en"), FACILITY_NAME_MAX)
REASON_ROW = RowSpec(
    "reasons",
    REASONS_MAX,
    ("title_ar", "title_en"),
    REASON_TITLE_MAX,
    ("text_ar", "text_en"),
    REASON_TEXT_MAX,
)


def _invalid(spec: RowSpec, message: str, **details: Any) -> DomainError:
    return DomainError("CENTER_ROWS_INVALID", message, section=spec.label, **details)


def parse_rows(rows: Sequence[object], spec: RowSpec) -> list[dict[str, str]]:
    """Normalized rows (every key present, text stripped) in the order given.

    Raises:
        DomainError: ``CENTER_ROWS_INVALID`` when there are too many rows, a row is not an
            object, carries an unknown key or a non-text value, has neither title, or a text
            is over its length.
    """
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise _invalid(spec, "Rows must be a list")
    if len(rows) > spec.max_rows:
        raise _invalid(spec, f"At most {spec.max_rows} rows", max_rows=spec.max_rows)
    out: list[dict[str, str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise _invalid(spec, "Each row must be an object", row=index)
        unknown = sorted(str(k) for k in row if k not in spec.keys)
        if unknown:
            raise _invalid(spec, "Unknown fields", row=index, fields=unknown)
        clean: dict[str, str] = {}
        for key in spec.keys:
            value = row.get(key, "")
            if value is None:
                value = ""
            if not isinstance(value, str):
                raise _invalid(spec, "Text expected", row=index, field=key)
            value = value.strip()
            limit = spec.title_max if key in spec.title else spec.text_max
            if len(value) > limit:
                raise _invalid(spec, "Text too long", row=index, field=key, max_length=limit)
            clean[key] = value
        if not any(clean[k] for k in spec.title):
            raise _invalid(spec, "Give a title in Arabic or English", row=index)
        out.append(clean)
    return out


def maps_link(raw: str) -> str:
    """A plain ``https://`` link to a map that the visitor's phone opens (like ``wa.me``):
    nothing is fetched or embedded by the page. Empty stays empty.

    Raises:
        DomainError: ``CENTER_MAPS_URL_INVALID`` (not https, no host, credentials in it,
            spaces, or longer than ``MAPS_URL_MAX``).
    """
    text = (raw or "").strip()
    if not text:
        return ""
    if len(text) > MAPS_URL_MAX or _SPACE.search(text) or not text.isascii():
        raise DomainError("CENTER_MAPS_URL_INVALID", "Give a map link starting with https://")
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise DomainError(
            "CENTER_MAPS_URL_INVALID", "Give a map link starting with https://"
        ) from None
    host = parts.hostname or ""
    if (
        parts.scheme != "https"
        or not host
        or "." not in host
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
    ):
        raise DomainError("CENTER_MAPS_URL_INVALID", "Give a map link starting with https://")
    return text


def approval_lapses_on_edit(before: Mapping[str, object], after: Mapping[str, object]) -> bool:
    """True when what the public would read changed (text or author): the approval was given to
    the old words, so the testimonial goes back to unapproved (ADR 0029 A6)."""
    keys = ("text_ar", "text_en", "author_ar", "author_en")
    return any(before.get(k) != after.get(k) for k in keys)
