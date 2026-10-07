"""Permission codes of the ``orders`` app (ARCHITECTURE 4.10). Imported by ``AppConfig.ready``.

Defaults follow FLOW.md roles; ``admin`` holds every code; doctors never hold billing codes.
``RolePermission`` rows override these defaults per role.
"""

from __future__ import annotations

from apps.core.permissions import register_permission
from apps.core.roles import (
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
    "orders.view",
    label_ar="عرض الطلبات وحالاتها",
    label_en="View orders and their status",
    default_roles={
        RECEPTIONIST,
        DOCTOR,
        CASHIER,
        CASHIER_SUPERVISOR,
        PHARMACIST,
        LAB_TECH,
        LAB_SUPERVISOR,
        NURSE,
        MANAGER,
        ADMIN,
    },
)

register_permission(
    "orders.create",
    label_ar="إنشاء طلبات (فحوصات، إجراءات، وصفات)",
    label_en="Create orders (tests, procedures, prescriptions)",
    default_roles={DOCTOR, ADMIN},
)

register_permission(
    "orders.cancel_line",
    label_ar="إلغاء سطر خدمة بسبب",
    label_en="Cancel a service line with a reason",
    default_roles={DOCTOR, CASHIER, CASHIER_SUPERVISOR, PHARMACIST, LAB_SUPERVISOR, MANAGER, ADMIN},
)

register_permission(
    "orders.authorize_perform_first",
    label_ar="تصريح التنفيذ قبل الدفع",
    label_en="Authorize perform-first exceptions",
    default_roles={CASHIER_SUPERVISOR, MANAGER, ADMIN},
)

register_permission(
    "orders.perform_procedure",
    label_ar="تنفيذ الإجراءات (تم)",
    label_en="Mark procedures done",
    default_roles={NURSE, DOCTOR, ADMIN},
)
