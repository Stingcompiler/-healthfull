"""Permission codes of the ``clinical`` app (ARCHITECTURE 4.10). Imported by ``AppConfig.ready``.

Defaults follow FLOW.md roles; ``admin`` holds every code; doctors never hold billing codes.
``RolePermission`` rows override these defaults per role.
"""

from __future__ import annotations

from apps.core.permissions import register_permission
from apps.core.roles import (
    ADMIN,
    DOCTOR,
    NURSE,
)

register_permission(
    "clinical.view",
    label_ar="عرض السجل السريري",
    label_en="View clinical records",
    default_roles={DOCTOR, NURSE, ADMIN},
)

register_permission(
    "clinical.write_note",
    label_ar="كتابة الملاحظة السريرية",
    label_en="Write clinical notes",
    default_roles={DOCTOR, ADMIN},
)

register_permission(
    "clinical.record_diagnosis",
    label_ar="تسجيل التشخيص",
    label_en="Record diagnoses",
    default_roles={DOCTOR, ADMIN},
)

register_permission(
    "clinical.manage_allergies",
    label_ar="إدارة الحساسية",
    label_en="Manage allergies",
    default_roles={DOCTOR, NURSE, ADMIN},
)

register_permission(
    "clinical.manage_conditions",
    label_ar="إدارة الأمراض المزمنة",
    label_en="Manage chronic conditions",
    default_roles={DOCTOR, ADMIN},
)

register_permission(
    "clinical.record_vitals",
    label_ar="تسجيل العلامات الحيوية",
    label_en="Record vitals",
    default_roles={DOCTOR, NURSE, ADMIN},
)

register_permission(
    "clinical.write_nursing_note",
    label_ar="كتابة ملاحظة تمريض",
    label_en="Write nursing notes",
    default_roles={NURSE, ADMIN},
)

register_permission(
    "clinical.refer",
    label_ar="كتابة إحالة",
    label_en="Write referrals",
    default_roles={DOCTOR, ADMIN},
)

register_permission(
    "clinical.manage_order_sets",
    label_ar="إدارة مجموعات الطلبات والمفضلة",
    label_en="Manage order sets and favorites",
    default_roles={DOCTOR, ADMIN},
)

register_permission(
    "clinical.manage_icd10",
    label_ar="إدارة جدول ICD-10",
    label_en="Manage the ICD-10 table",
    default_roles={ADMIN},
)

register_permission(
    "clinical.view_estimated_cost",
    label_ar="عرض التكلفة التقديرية للطبيب",
    label_en="See estimated cost while ordering",
    default_roles={ADMIN},
)
