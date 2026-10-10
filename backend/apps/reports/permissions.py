"""Permission codes of the ``reports`` app (ARCHITECTURE 4.10). Imported by ``AppConfig.ready``.

One ``reports.view_<area>`` code per catalog area (ADR 0013); each report endpoint and its
Excel export require exactly that code (an export shows the same rows as the screen).
Defaults follow FLOW.md roles: the manager, the accountant and the admin read the money
reports; the cashier supervisor (who confirms transfers and reviews shifts) reads them too.
Doctors, cashiers, receptionists and nurses hold none of the money codes. ``admin`` holds
every code. ``RolePermission`` rows override these defaults per role.
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
    "reports.view_dashboard",
    label_ar="لوحة المدير",
    label_en="Manager dashboard",
    default_roles={MANAGER, ADMIN},
)

register_permission(
    "reports.view_finance",
    label_ar="التقارير المالية: الإيراد والورديات والتحويلات والخصومات وحصص الجهات",
    label_en="Finance reports: revenue, shifts, transfers, adjustments and payer receivables",
    default_roles={CASHIER_SUPERVISOR, ACCOUNTANT, MANAGER, ADMIN},
)

register_permission(
    "reports.view_exceptions",
    label_ar="تقارير الاستثناءات: مطلوب غير مفوتر، مدفوع غير منفذ، منفذ بتصريح",
    label_en="Exception reports: requested not invoiced, paid not performed, by authorization",
    default_roles={CASHIER_SUPERVISOR, ACCOUNTANT, MANAGER, ADMIN},
)

register_permission(
    "reports.view_stock",
    label_ar="تقارير المخزون: القيمة والحركة والفروق والصلاحية",
    label_en="Stock reports: valuation, movement, variance and expiry",
    default_roles={PHARMACIST, ACCOUNTANT, MANAGER, ADMIN},
)

register_permission(
    "reports.view_visits",
    label_ar="تقارير الزيارات حسب القسم والطبيب واليوم",
    label_en="Visit reports by department, doctor and day",
    default_roles={MANAGER, ADMIN},
)

register_permission(
    "reports.view_lab",
    label_ar="تقرير زمن إنجاز المعمل وحجمه",
    label_en="Lab turnaround and volume report",
    default_roles={LAB_SUPERVISOR, MANAGER, ADMIN},
)
