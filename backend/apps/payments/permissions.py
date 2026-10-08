"""Permission codes of the ``payments`` app (ARCHITECTURE 4.10). Imported by ``AppConfig.ready``.

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
)

register_permission(
    "payments.view",
    label_ar="عرض المدفوعات",
    label_en="View payments",
    default_roles={CASHIER, CASHIER_SUPERVISOR, ACCOUNTANT, MANAGER, ADMIN},
)

register_permission(
    "payments.take_payment",
    label_ar="تحصيل المدفوعات",
    label_en="Take payments",
    default_roles={CASHIER, CASHIER_SUPERVISOR, ADMIN},
)

register_permission(
    "payments.confirm_transfer",
    label_ar="تأكيد التحويلات البنكية",
    label_en="Confirm bank transfers",
    default_roles={CASHIER_SUPERVISOR, ACCOUNTANT, ADMIN},
)

register_permission(
    "payments.reject_transfer",
    label_ar="رفض التحويلات البنكية",
    label_en="Reject bank transfers",
    default_roles={CASHIER_SUPERVISOR, ACCOUNTANT, ADMIN},
)

register_permission(
    "payments.override_duplicate",
    label_ar="تجاوز مرجع تحويل مكرر",
    label_en="Override a duplicate transfer reference",
    default_roles={CASHIER_SUPERVISOR, ADMIN},
)

register_permission(
    "payments.request_refund",
    label_ar="طلب استرداد",
    label_en="Request refunds",
    default_roles={CASHIER, CASHIER_SUPERVISOR, ADMIN},
)

register_permission(
    "payments.approve_refund",
    label_ar="اعتماد الاسترداد",
    label_en="Approve refunds",
    default_roles={CASHIER_SUPERVISOR, ACCOUNTANT, ADMIN},
)

register_permission(
    "payments.pay_refund",
    label_ar="صرف الاسترداد من الوردية",
    label_en="Pay refunds from the shift",
    default_roles={CASHIER, CASHIER_SUPERVISOR, ADMIN},
)

register_permission(
    "payments.open_shift",
    label_ar="فتح وردية",
    label_en="Open a shift",
    default_roles={CASHIER, CASHIER_SUPERVISOR, ADMIN},
)

register_permission(
    "payments.close_shift",
    label_ar="إغلاق وردية",
    label_en="Close a shift",
    default_roles={CASHIER, CASHIER_SUPERVISOR, ADMIN},
)

register_permission(
    "payments.cash_handover",
    label_ar="تسليم النقد",
    label_en="Hand over cash",
    default_roles={CASHIER, CASHIER_SUPERVISOR, ADMIN},
)

register_permission(
    "payments.receive_handover",
    label_ar="استلام النقد",
    label_en="Receive handed-over cash",
    default_roles={CASHIER, CASHIER_SUPERVISOR, ACCOUNTANT, MANAGER, ADMIN},
)

register_permission(
    "payments.view_all_shifts",
    label_ar="عرض كل الورديات",
    label_en="View every shift",
    default_roles={CASHIER_SUPERVISOR, ACCOUNTANT, MANAGER, ADMIN},
)

register_permission(
    "payments.review_shift",
    label_ar="مراجعة الوردية واعتمادها",
    label_en="Review and sign off shifts",
    default_roles={CASHIER_SUPERVISOR, ACCOUNTANT, MANAGER, ADMIN},
)

register_permission(
    "payments.manage_banks",
    label_ar="إدارة البنوك والخزائن",
    label_en="Manage banks and tills",
    default_roles={ACCOUNTANT, ADMIN},
)
