"""Resolution of a user's effective permission codes from roles, defaults and overrides.

Semantics (ARCHITECTURE 4.10):

* Each permission code has a set of default roles.
* A per-(role, code) override, when present, replaces the default for that role only
  (``True`` grants, ``False`` revokes).
* A user holds a code if *any* of their roles grants it. A revoke on one role never
  removes a grant coming from another role.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass

from domain.errors import DomainError

__all__ = ["MatrixChange", "MatrixPlan", "plan_matrix_update", "resolve_permissions", "role_grants"]


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


# --- Editing the matrix (FEATURES 0.3) ------------------------------------------------------


@dataclass(frozen=True, slots=True, order=True)
class MatrixChange:
    """The wanted state of one cell of the matrix: does ``role`` grant ``code``."""

    role: str
    code: str
    allowed: bool


@dataclass(frozen=True, slots=True)
class MatrixPlan:
    """Override rows to write so the matrix shows the wanted cells.

    ``upserts`` maps ``(role, code)`` to the override value to store, ``deletes`` lists the
    overrides to remove (the cell goes back to its default), and ``changed`` the cells whose
    effective grant flips (for the audit trail), sorted by role then code.
    """

    upserts: dict[tuple[str, str], bool]
    deletes: frozenset[tuple[str, str]]
    changed: tuple[MatrixChange, ...]


def plan_matrix_update(
    defaults: Mapping[str, frozenset[str]],
    overrides: Mapping[tuple[str, str], bool],
    changes: Iterable[MatrixChange],
    *,
    roles: Collection[str],
    protected: Collection[tuple[str, str]] = (),
) -> MatrixPlan:
    """Plan the override rows for an edit of the permission matrix.

    A cell whose wanted grant equals its default keeps no override (it follows the default
    again); any other wanted grant is stored as an override. Cells not named in ``changes``
    are left alone. ``protected`` cells may never be revoked, so an administrator cannot
    lock everyone out of the matrix itself.

    Raises:
        DomainError: ``PERMISSION_UNKNOWN`` (code not in the registry), ``ROLE_UNKNOWN``,
            ``MATRIX_CHANGE_CONFLICT`` (one cell asked both ways), ``PERMISSION_PROTECTED``.
    """
    known_roles = frozenset(roles)
    wanted: dict[tuple[str, str], bool] = {}
    for change in changes:
        if change.code not in defaults:
            raise DomainError(
                "PERMISSION_UNKNOWN", "Unknown permission code", permission=change.code
            )
        if change.role not in known_roles:
            raise DomainError("ROLE_UNKNOWN", "Unknown role code", role=change.role)
        key = (change.role, change.code)
        if wanted.get(key, change.allowed) is not change.allowed:
            raise DomainError(
                "MATRIX_CHANGE_CONFLICT",
                "The same permission is both granted and revoked for a role",
                role=change.role,
                permission=change.code,
            )
        if key in protected and not change.allowed:
            raise DomainError(
                "PERMISSION_PROTECTED",
                "This permission cannot be revoked from this role",
                role=change.role,
                permission=change.code,
            )
        wanted[key] = change.allowed

    upserts: dict[tuple[str, str], bool] = {}
    deletes: set[tuple[str, str]] = set()
    changed: list[MatrixChange] = []
    for (role, code), allowed in wanted.items():
        if role_grants(role, code, defaults, overrides) is not allowed:
            changed.append(MatrixChange(role, code, allowed))
        is_default = (role in defaults[code]) is allowed
        stored = overrides.get((role, code))
        if is_default:
            if stored is not None:
                deletes.add((role, code))
        elif stored is not allowed:
            upserts[(role, code)] = allowed
    return MatrixPlan(upserts=upserts, deletes=frozenset(deletes), changed=tuple(sorted(changed)))
