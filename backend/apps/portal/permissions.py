"""Permission codes of the ``portal`` app (ARCHITECTURE 4.10). Imported by ``AppConfig.ready``.

Defaults follow FLOW.md roles; ``admin`` holds every code; doctors never hold billing codes.
``RolePermission`` rows override these defaults per role.
"""

from __future__ import annotations

from apps.core.permissions import register_permission
from apps.core.roles import (
    ADMIN,
    CASHIER,
    CASHIER_SUPERVISOR,
    LAB_SUPERVISOR,
    MANAGER,
    RECEPTIONIST,
)

register_permission(
    "portal.issue_access_code",
    label_ar="إصدار رمز دخول البوابة",
    label_en="Issue portal access codes",
    # The cashier prints the code on the receipt (FEATURES 15.1, ADR 0016).
    default_roles={RECEPTIONIST, CASHIER, CASHIER_SUPERVISOR, LAB_SUPERVISOR, ADMIN},
)

register_permission(
    "portal.revoke_access_code",
    label_ar="إلغاء رمز دخول البوابة",
    label_en="Revoke portal access codes",
    default_roles={RECEPTIONIST, MANAGER, ADMIN},
)
