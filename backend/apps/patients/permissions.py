"""Permission codes of the ``patients`` app (ARCHITECTURE 4.10). Imported by ``AppConfig.ready``.

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
    "patients.view",
    label_ar="عرض ملفات المرضى",
    label_en="View patient files",
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
    "patients.create",
    label_ar="تسجيل مريض جديد",
    label_en="Register new patients",
    default_roles={RECEPTIONIST, CASHIER, CASHIER_SUPERVISOR, PHARMACIST, ADMIN},
)

register_permission(
    "patients.register_emergency",
    label_ar="تسجيل مريض طوارئ بالاسم والجنس",
    label_en="Emergency registration (name and sex only)",
    default_roles={RECEPTIONIST, NURSE, DOCTOR, ADMIN},
)

register_permission(
    "patients.edit",
    label_ar="تعديل بيانات المريض",
    label_en="Edit patient details",
    default_roles={RECEPTIONIST, ADMIN},
)

register_permission(
    "patients.merge",
    label_ar="دمج الملفات المكررة",
    label_en="Merge duplicate patient files",
    default_roles={MANAGER, ADMIN},
)

register_permission(
    "patients.manage_coverage",
    label_ar="إدارة تغطية المريض",
    label_en="Manage patient coverage on file",
    default_roles={RECEPTIONIST, CASHIER, CASHIER_SUPERVISOR, ACCOUNTANT, ADMIN},
)

register_permission(
    "patients.view_balance",
    label_ar="عرض رصيد المريض",
    label_en="View patient credit balance",
    default_roles={CASHIER, CASHIER_SUPERVISOR, ACCOUNTANT, MANAGER, ADMIN},
)
