"""Resolution of a user's effective permission codes from roles, defaults and overrides.

Semantics (ARCHITECTURE 4.10):

* Each permission code has a set of default roles.
* A per-(role, code) override, when present, replaces the default for that role only
  (``True`` grants, ``False`` revokes).
* A user holds a code if *any* of their roles grants it. A revoke on one role never
  removes a grant coming from another role.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

__all__ = ["resolve_permissions", "role_grants"]


def role_grants(
    role: str,
    code: str,
    defaults: Mapping[str, frozenset[str]],
    overrides: Mapping[tuple[str, str], bool],
) -> bool:
    """Whether ``role`` grants ``code`` after applying any override."""
    override = overrides.get((role, code))
    if override is not None:
        return override
    return role in defaults.get(code, frozenset())


def resolve_permissions(
    roles: Iterable[str],
    defaults: Mapping[str, frozenset[str]],
    overrides: Mapping[tuple[str, str], bool],
) -> frozenset[str]:
    """Effective codes for a holder of ``roles``.

    Only codes present in ``defaults`` (the registry) can be granted; overrides for
    unknown codes are ignored.
    """
    role_set = frozenset(roles)
    return frozenset(
        code
        for code in defaults
        if any(role_grants(role, code, defaults, overrides) for role in role_set)
    )
