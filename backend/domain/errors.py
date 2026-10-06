"""Domain error type shared by every rule in the system.

The API layer maps a :class:`DomainError` to HTTP 409 (unless the code is listed in
``api.errors.DOMAIN_ERROR_STATUS``) with the body ``{code, message, details}``.
The frontend translates ``code`` through its ``errors`` namespace, so codes are a
stable public contract: UPPER_SNAKE_CASE, never reworded once shipped.
"""

from __future__ import annotations

import re
from typing import Any

_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class DomainError(Exception):
    """A business rule was violated.

    Args:
        code: Stable machine-readable code, e.g. ``"INVOICE_FROZEN"``.
        message: Human-readable explanation (English, for logs and developers).
        **details: Extra JSON-serialisable context for the client.
    """

    code: str
    message: str
    details: dict[str, Any]

    def __init__(self, code: str, message: str = "", **details: Any) -> None:
        if not _CODE_RE.match(code):
            raise ValueError(f"DomainError code must be UPPER_SNAKE_CASE, got {code!r}")
        self.code = code
        self.message = message or code
        self.details = dict(details)
        super().__init__(self.message)

    def as_dict(self) -> dict[str, Any]:
        """Return the wire representation ``{code, message, details}``."""
        return {"code": self.code, "message": self.message, "details": dict(self.details)}

    def __repr__(self) -> str:
        return (
            f"DomainError(code={self.code!r}, message={self.message!r}, details={self.details!r})"
        )
