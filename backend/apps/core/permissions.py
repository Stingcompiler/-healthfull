"""Permission registry (ARCHITECTURE 4.10).

Permission codes are ``"<app>.<action>"`` strings. Each app registers its codes at import
time of its own ``permissions`` module (imported from its ``AppConfig.ready``)::

    from apps.core.permissions import register_permission
    from apps.core import roles

    register_permission(
        "billing.approve_invoice",
        label_ar="اعتماد الفاتورة",
        label_en="Approve invoice",
        default_roles={roles.CASHIER, roles.CASHIER_SUPERVISOR},
    )

``RolePermission`` rows override the defaults per role (the editable matrix).
:func:`effective_permissions` returns the codes a user holds.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ImproperlyConfigured

from apps.core import roles
from apps.core.roles import ROLE_CODES
from domain.permissions import resolve_permissions

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser

    from apps.core.models import User

_CODE_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class PermissionDef:
    code: str
    label_ar: str
    label_en: str
    default_roles: frozenset[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label_ar": self.label_ar,
            "label_en": self.label_en,
            "default_roles": sorted(self.default_roles),
        }


_REGISTRY: dict[str, PermissionDef] = {}

#: Read-only view of the registry: ``code -> PermissionDef``.
PERMISSIONS = MappingProxyType(_REGISTRY)


def register_permission(
    code: str,
    *,
    label_ar: str,
    label_en: str,
    default_roles: Iterable[str] = (),
) -> PermissionDef:
    """Register a permission code. Re-registering an identical definition is a no-op."""
    if not _CODE_RE.match(code):
        raise ImproperlyConfigured(f"Permission code must look like 'app.action', got {code!r}")
    if not label_ar.strip() or not label_en.strip():
        raise ImproperlyConfigured(f"Permission {code!r} needs both Arabic and English labels")
    role_set = frozenset(default_roles)
    unknown = role_set - ROLE_CODES
    if unknown:
        raise ImproperlyConfigured(f"Permission {code!r} has unknown roles: {sorted(unknown)}")
    definition = PermissionDef(code, label_ar, label_en, role_set)
    existing = _REGISTRY.get(code)
    if existing is not None and existing != definition:
        raise ImproperlyConfigured(f"Permission {code!r} is already registered differently")
    _REGISTRY[code] = definition
    return definition


def is_registered(code: str) -> bool:
    return code in _REGISTRY


def get_permission(code: str) -> PermissionDef:
    try:
        return _REGISTRY[code]
    except KeyError:
        raise ImproperlyConfigured(f"Permission {code!r} is not registered") from None


def effective_permissions(user: User | AnonymousUser | None) -> frozenset[str]:
    """Permission codes held by ``user``.

    Anonymous and inactive users hold nothing. Superusers hold every registered code
    (break-glass account). Everyone else gets the union over their roles, with
    ``RolePermission`` overrides applied per role.
    """
    from apps.core.models import RolePermission

    if user is None or not user.is_authenticated or not user.is_active:
        return frozenset()
    if user.is_superuser:
        return frozenset(_REGISTRY)
    role_codes = list(user.roles.values_list("code", flat=True))
    if not role_codes:
        return frozenset()
    overrides = {
        (role_code, code): allowed
        for role_code, code, allowed in RolePermission.objects.filter(
            role__code__in=role_codes
        ).values_list("role__code", "code", "allowed")
    }
    defaults = {code: perm.default_roles for code, perm in _REGISTRY.items()}
    return resolve_permissions(role_codes, defaults, overrides)


def roles_holding(code: str) -> frozenset[str]:
    """Role codes that grant ``code`` on their own (defaults with ``RolePermission``
    overrides applied). Lets a caller narrow a user list in one query before checking each
    remaining user with :func:`effective_permissions`."""
    from apps.core.models import Role, RolePermission

    codes = list(Role.objects.values_list("code", flat=True))
    overrides = {
        (role_code, c): allowed
        for role_code, c, allowed in RolePermission.objects.filter(code=code).values_list(
            "role__code", "code", "allowed"
        )
    }
    defaults = {c: perm.default_roles for c, perm in _REGISTRY.items()}
    return frozenset(r for r in codes if code in resolve_permissions([r], defaults, overrides))


# --- Core and ops codes ------------------------------------------------------------------

register_permission(
    "core.manage_users",
    label_ar="إدارة المستخدمين",
    label_en="Manage users",
    default_roles={roles.ADMIN},
)
register_permission(
    "core.manage_roles",
    label_ar="إدارة الأدوار ومصفوفة الصلاحيات",
    label_en="Manage roles and permission matrix",
    default_roles={roles.ADMIN},
)
register_permission(
    "core.manage_settings",
    label_ar="إدارة إعدادات المركز والسياسات",
    label_en="Manage center settings and policies",
    default_roles={roles.ADMIN, roles.MANAGER},
)
register_permission(
    "core.view_audit",
    label_ar="عرض سجل التدقيق",
    label_en="View audit trail",
    default_roles={roles.ADMIN, roles.MANAGER, roles.ACCOUNTANT},
)
register_permission(
    "ops.view_status",
    label_ar="عرض حالة النظام والنسخ الاحتياطي",
    label_en="View system and backup status",
    default_roles={roles.ADMIN, roles.MANAGER},
)
register_permission(
    "core.manage_departments",
    label_ar="إدارة الأقسام والغرف والأطباء",
    label_en="Manage departments, rooms and doctors",
    default_roles={roles.ADMIN},
)
register_permission(
    "core.manage_reason_codes",
    label_ar="إدارة قوائم الأسباب",
    label_en="Manage reason lists",
    default_roles={roles.ADMIN, roles.MANAGER},
)
register_permission(
    "core.manage_print_templates",
    label_ar="إدارة قوالب الطباعة",
    label_en="Manage print templates",
    default_roles={roles.ADMIN},
)
