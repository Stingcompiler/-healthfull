"""Permission codes of the ``catalog`` app (ARCHITECTURE 4.10). Imported by ``AppConfig.ready``.

Defaults follow FLOW.md roles; ``admin`` holds every code; doctors never hold billing codes.
``RolePermission`` rows override these defaults per role.
"""

from __future__ import annotations

from apps.core.permissions import register_permission
from apps.core.roles import (
    ACCOUNTANT,
    ADMIN,
    CASHIER,
    CASHIER_SUPERVISOR,
    DOCTOR,
    LAB_SUPERVISOR,
    LAB_TECH,
    MANAGER,
    NURSE,
    PHARMACIST,
    RECEPTIONIST,
)

register_permission(
    "catalog.view",
    label_ar="عرض دليل الخدمات",
    label_en="View the service catalog",
    default_roles={
        RECEPTIONIST,
        DOCTOR,
        CASHIER,
        CASHIER_SUPERVISOR,
        PHARMACIST,
        LAB_TECH,
        LAB_SUPERVISOR,
        NURSE,
        ACCOUNTANT,
        MANAGER,
        ADMIN,
    },
)

register_permission(
    "catalog.manage",
    label_ar="إدارة دليل الخدمات",
    label_en="Manage the service catalog",
    default_roles={ADMIN},
)

register_permission(
    "catalog.view_prices",
    label_ar="عرض الأسعار",
    label_en="View prices",
    default_roles={
        RECEPTIONIST,
        CASHIER,
        CASHIER_SUPERVISOR,
        PHARMACIST,
        ACCOUNTANT,
        MANAGER,
        ADMIN,
    },
)

register_permission(
    "catalog.manage_prices",
    label_ar="إدارة قوائم الأسعار",
    label_en="Manage price lists",
    default_roles={ACCOUNTANT, MANAGER, ADMIN},
)

register_permission(
    "catalog.manage_payers",
    label_ar="إدارة جهات التغطية وقواعدها",
    label_en="Manage payers and coverage rules",
    default_roles={ACCOUNTANT, MANAGER, ADMIN},
)
