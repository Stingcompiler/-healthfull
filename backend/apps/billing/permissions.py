"""Permission codes of the ``billing`` app (ARCHITECTURE 4.10). Imported by ``AppConfig.ready``.

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
    MANAGER,
    PHARMACIST,
)

register_permission(
    "billing.view",
    label_ar="عرض الفواتير",
    label_en="View invoices",
    default_roles={CASHIER, CASHIER_SUPERVISOR, ACCOUNTANT, MANAGER, ADMIN},
)

register_permission(
    "billing.create_invoice",
    label_ar="إنشاء فاتورة من الطلبات",
    label_en="Create invoices from orders",
    default_roles={CASHIER, CASHIER_SUPERVISOR, ADMIN},
)

register_permission(
    "billing.approve_invoice",
    label_ar="اعتماد الفاتورة",
    label_en="Approve invoices",
    default_roles={CASHIER, CASHIER_SUPERVISOR, ADMIN},
)

register_permission(
    "billing.void_draft",
    label_ar="إلغاء فاتورة مسودة",
    label_en="Void draft invoices",
    default_roles={CASHIER, CASHIER_SUPERVISOR, ADMIN},
)

register_permission(
    "billing.apply_discount",
    label_ar="تطبيق خصم أو إعفاء في حدود الدور",
    label_en="Apply discounts within the role limit",
    default_roles={CASHIER, CASHIER_SUPERVISOR, ACCOUNTANT, MANAGER, ADMIN},
)

register_permission(
    "billing.override_discount_limit",
    label_ar="اعتماد خصم فوق الحد",
    label_en="Approve discounts above the limit",
    default_roles={CASHIER_SUPERVISOR, MANAGER, ADMIN},
)

register_permission(
    "billing.create_credit_note",
    label_ar="إنشاء إشعار دائن",
    label_en="Create credit notes",
    default_roles={CASHIER, CASHIER_SUPERVISOR, ACCOUNTANT, ADMIN},
)

register_permission(
    "billing.approve_credit_note",
    label_ar="اعتماد إشعار دائن",
    label_en="Approve credit notes",
    default_roles={CASHIER_SUPERVISOR, ACCOUNTANT, ADMIN},
)

register_permission(
    "billing.pharmacy_sale",
    label_ar="بيع صيدلية مباشر",
    label_en="Walk-in pharmacy sales",
    default_roles={PHARMACIST, CASHIER, CASHIER_SUPERVISOR, ADMIN},
)
