"""Permission codes of the ``reports`` app (ARCHITECTURE 4.10). Imported by ``AppConfig.ready``.

Defaults follow FLOW.md roles; ``admin`` holds every code; doctors never hold billing codes.
``RolePermission`` rows override these defaults per role.
"""

from __future__ import annotations

from apps.core.permissions import register_permission
from apps.core.roles import (
    ACCOUNTANT,
    ADMIN,
    CASHIER_SUPERVISOR,
    LAB_SUPERVISOR,
    MANAGER,
    PHARMACIST,
)

register_permission(
    "reports.view",
    label_ar="عرض التقارير",
    label_en="View reports",
    default_roles={CASHIER_SUPERVISOR, ACCOUNTANT, MANAGER, ADMIN},
)

register_permission(
    "reports.dashboard",
    label_ar="لوحة المدير",
    label_en="Manager dashboard",
    default_roles={MANAGER, ADMIN},
)

register_permission(
    "reports.financial",
    label_ar="التقارير المالية",
    label_en="Financial reports",
    default_roles={CASHIER_SUPERVISOR, ACCOUNTANT, MANAGER, ADMIN},
)

register_permission(
    "reports.operational",
    label_ar="تقارير الزيارات والعمليات",
    label_en="Visit and operations reports",
    default_roles={MANAGER, ADMIN},
)

register_permission(
    "reports.stock",
    label_ar="تقارير المخزون",
    label_en="Stock reports",
    default_roles={PHARMACIST, ACCOUNTANT, MANAGER, ADMIN},
)

register_permission(
    "reports.lab",
    label_ar="تقارير المعمل",
    label_en="Lab reports",
    default_roles={LAB_SUPERVISOR, MANAGER, ADMIN},
)

register_permission(
    "reports.export",
    label_ar="تصدير التقارير Excel وPDF",
    label_en="Export reports to Excel and PDF",
    default_roles={ACCOUNTANT, MANAGER, ADMIN},
)
