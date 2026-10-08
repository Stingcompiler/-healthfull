"""Permission codes of the ``lab`` app (ARCHITECTURE 4.10). Imported by ``AppConfig.ready``.

Defaults follow FLOW.md roles; ``admin`` holds every code; doctors never hold billing codes.
``RolePermission`` rows override these defaults per role.
"""

from __future__ import annotations

from apps.core.permissions import register_permission
from apps.core.roles import (
    ADMIN,
    DOCTOR,
    LAB_SUPERVISOR,
    LAB_TECH,
    NURSE,
    RECEPTIONIST,
)

register_permission(
    "lab.view_worklist",
    label_ar="عرض قائمة عمل المعمل",
    label_en="View the lab work list",
    default_roles={LAB_TECH, LAB_SUPERVISOR, ADMIN},
)

register_permission(
    "lab.collect_sample",
    label_ar="سحب العينة",
    label_en="Collect samples",
    default_roles={LAB_TECH, LAB_SUPERVISOR, NURSE, ADMIN},
)

register_permission(
    "lab.receive_sample",
    label_ar="استلام العينة ورفضها",
    label_en="Receive or reject samples",
    default_roles={LAB_TECH, LAB_SUPERVISOR, ADMIN},
)

register_permission(
    "lab.enter_results",
    label_ar="إدخال النتائج",
    label_en="Enter results",
    default_roles={LAB_TECH, LAB_SUPERVISOR, ADMIN},
)

register_permission(
    "lab.approve_results",
    label_ar="اعتماد النتائج",
    label_en="Approve results",
    default_roles={LAB_SUPERVISOR, ADMIN},
)

register_permission(
    "lab.amend_results",
    label_ar="تعديل نتيجة معتمدة",
    label_en="Amend approved results",
    default_roles={LAB_SUPERVISOR, ADMIN},
)

register_permission(
    "lab.view_results",
    label_ar="عرض النتائج المعتمدة",
    label_en="View approved results",
    default_roles={DOCTOR, NURSE, LAB_TECH, LAB_SUPERVISOR, ADMIN},
)

register_permission(
    "lab.print_results",
    label_ar="طباعة النتائج",
    label_en="Print results",
    default_roles={RECEPTIONIST, DOCTOR, LAB_TECH, LAB_SUPERVISOR, ADMIN},
)

register_permission(
    "lab.manage_tests",
    label_ar="إدارة دليل الفحوصات والمعايير",
    label_en="Manage tests, parameters and ranges",
    default_roles={LAB_SUPERVISOR, ADMIN},
)
