"""A parsed sheet row before it is stored as an ``ImportRow`` (shared by the import kinds)."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any

from apps.imports.models import RowStatus

__all__ = ["RowDraft", "row_status"]


@dataclass(slots=True)
class RowDraft:
    row_no: int
    data: dict[str, Any]
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    duplicate_of: int | None = None


def row_status(draft: RowDraft, duplicate_hints: Collection[str]) -> RowStatus:
    """Error rows never import; possible duplicates only when asked; other hints are
    informational (``warning``: imported like a valid row)."""
    if draft.errors:
        return RowStatus.ERROR
    if any(w.get("code") in duplicate_hints for w in draft.warnings):
        return RowStatus.DUPLICATE
    if draft.warnings:
        return RowStatus.WARNING
    return RowStatus.VALID
