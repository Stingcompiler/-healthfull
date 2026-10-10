"""Permission codes of the ``visits`` app (ARCHITECTURE 4.10). Imported by ``AppConfig.ready``.

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
    DISPLAY,
    DOCTOR,
    LAB_SUPERVISOR,
    LAB_TECH,
    MANAGER,
    NURSE,
    PHARMACIST,
    RECEPTIONIST,
)

register_permission(
    "visits.view",
    label_ar="عرض الزيارات",
    label_en="View visits",
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
    "visits.create",
    label_ar="إنشاء زيارة",
    label_en="Create visits",
    default_roles={RECEPTIONIST, ADMIN},
)

register_permission(
    "visits.cancel",
    label_ar="إلغاء زيارة",
    label_en="Cancel visits",
    default_roles={RECEPTIONIST, CASHIER_SUPERVISOR, MANAGER, ADMIN},
)

register_permission(
    "visits.close",
    label_ar="ختم الزيارة",
    label_en="Close visits",
    default_roles={DOCTOR, ADMIN},
)

register_permission(
    "visits.view_queue",
    label_ar="عرض طابور العيادة",
    label_en="View the clinic queue",
    default_roles={RECEPTIONIST, DOCTOR, NURSE, MANAGER, ADMIN},
)

register_permission(
    "visits.view_display",
    label_ar="عرض شاشة الانتظار",
    label_en="Waiting-room display feed",
    # The kiosk account's only permission (ADR 0019); staff who had the queue keep the screen.
    default_roles={DISPLAY, RECEPTIONIST, DOCTOR, NURSE, MANAGER, ADMIN},
)

register_permission(
    "visits.manage_queue",
    label_ar="إدارة الطابور (نداء، بدء، انتهاء)",
    label_en="Manage the queue (call, start, done)",
    default_roles={RECEPTIONIST, DOCTOR, NURSE, ADMIN},
)

register_permission(
    "visits.finish_consultation",
    label_ar="إنهاء الكشف (يُسجَّل الكشف منفَّذاً)",
    label_en="Finish a consultation (marks the consultation performed)",
    default_roles={DOCTOR, ADMIN},
)

register_permission(
    "visits.manage_appointments",
    label_ar="إدارة المواعيد",
    label_en="Manage appointments",
    default_roles={RECEPTIONIST, MANAGER, ADMIN},
)

register_permission(
    "visits.manage_schedules",
    label_ar="إدارة جداول الأطباء",
    label_en="Manage doctor schedules",
    default_roles={MANAGER, ADMIN},
)

register_permission(
    "visits.admit",
    label_ar="تنويم مريض",
    label_en="Admit a patient",
    # Nurses record the admission on the bed board on the doctor's decision (FEATURES 10.5).
    default_roles={RECEPTIONIST, DOCTOR, NURSE, ADMIN},
)

register_permission(
    "visits.manage_beds",
    label_ar="إدارة الأسرة",
    label_en="Manage beds and bed assignments",
    default_roles={NURSE, MANAGER, ADMIN},
)

register_permission(
    "visits.discharge",
    label_ar="خروج مريض منوم",
    label_en="Discharge an inpatient",
    default_roles={DOCTOR, NURSE, ADMIN},
)

register_permission(
    "visits.cancel_admission",
    label_ar="إلغاء تنويم تم بالخطأ",
    label_en="Cancel an admission made in error",
    # The ward nurse who recorded it; a second person approves (ADR 0018).
    default_roles={NURSE, MANAGER, ADMIN},
)

register_permission(
    "visits.approve_admission_cancel",
    label_ar="اعتماد إلغاء تنويم تم بالخطأ",
    label_en="Approve cancelling an admission made in error",
    default_roles={CASHIER_SUPERVISOR, MANAGER, ADMIN},
)
