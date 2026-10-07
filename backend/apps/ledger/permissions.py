"""Permission codes of the ``ledger`` app (ARCHITECTURE 4.10). Imported by ``AppConfig.ready``.

Defaults follow FLOW.md roles; ``admin`` holds every code; doctors never hold billing codes.
``RolePermission`` rows override these defaults per role.
"""

from __future__ import annotations

from apps.core.permissions import register_permission
from apps.core.roles import (
    ACCOUNTANT,
    ADMIN,
    MANAGER,
)

register_permission(
    "ledger.view",
    label_ar="عرض دفتر الأستاذ",
    label_en="View the ledger",
    default_roles={ACCOUNTANT, MANAGER, ADMIN},
)

register_permission(
    "ledger.manage_accounts",
    label_ar="تعديل أسماء الحسابات",
    label_en="Edit account names",
    default_roles={ADMIN},
)
