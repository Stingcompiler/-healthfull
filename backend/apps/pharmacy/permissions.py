"""Permission codes of the ``pharmacy`` app (ARCHITECTURE 4.10). Imported by ``AppConfig.ready``.

Defaults follow FLOW.md roles; ``admin`` holds every code; doctors never hold billing codes.
``RolePermission`` rows override these defaults per role.
"""

from __future__ import annotations

from apps.core.permissions import register_permission
from apps.core.roles import (
    ACCOUNTANT,
    ADMIN,
    MANAGER,
    PHARMACIST,
)

register_permission(
    "pharmacy.view",
    label_ar="عرض الصيدلية والمخزون",
    label_en="View pharmacy and stock",
    default_roles={PHARMACIST, MANAGER, ACCOUNTANT, ADMIN},
)

register_permission(
    "pharmacy.dispense",
    label_ar="صرف الوصفات",
    label_en="Dispense prescriptions",
    default_roles={PHARMACIST, ADMIN},
)

register_permission(
    "pharmacy.override_batch",
    label_ar="صرف من دفعة غير المقترحة",
    label_en="Dispense from a non-FEFO batch",
    default_roles={PHARMACIST, ADMIN},
)

register_permission(
    "pharmacy.receive_goods",
    label_ar="استلام البضاعة",
    label_en="Receive goods",
    default_roles={PHARMACIST, ADMIN},
)

register_permission(
    "pharmacy.request_adjustment",
    label_ar="طلب تسوية مخزون",
    label_en="Request stock adjustments",
    default_roles={PHARMACIST, ADMIN},
)

register_permission(
    "pharmacy.approve_adjustment",
    label_ar="اعتماد تسوية المخزون",
    label_en="Approve stock adjustments",
    default_roles={MANAGER, ADMIN},
)

register_permission(
    "pharmacy.count_stock",
    label_ar="جرد المخزون",
    label_en="Count stock",
    default_roles={PHARMACIST, ADMIN},
)

register_permission(
    "pharmacy.post_count",
    label_ar="ترحيل فروق الجرد",
    label_en="Post stock count corrections",
    default_roles={MANAGER, ADMIN},
)

register_permission(
    "pharmacy.transfer_stock",
    label_ar="تحويل بين المخازن",
    label_en="Transfer stock between stores",
    default_roles={PHARMACIST, ADMIN},
)

register_permission(
    "pharmacy.manage_items",
    label_ar="إدارة الأصناف والوحدات",
    label_en="Manage items and units",
    default_roles={PHARMACIST, ADMIN},
)

register_permission(
    "pharmacy.manage_suppliers",
    label_ar="إدارة الموردين",
    label_en="Manage suppliers",
    default_roles={PHARMACIST, MANAGER, ADMIN},
)

register_permission(
    "pharmacy.manage_stores",
    label_ar="إدارة المخازن",
    label_en="Manage stores",
    default_roles={ADMIN},
)
