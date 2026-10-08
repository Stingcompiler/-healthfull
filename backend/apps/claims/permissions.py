"""Permission codes of the ``claims`` app (ARCHITECTURE 4.10). Imported by ``AppConfig.ready``.

Defaults follow FLOW.md roles; ``admin`` holds every code; doctors never hold billing codes.
``RolePermission`` rows override these defaults per role.
"""

from __future__ import annotations

from apps.core.permissions import register_permission
from apps.core.roles import (
    ACCOUNTANT,
    ADMIN,
    MANAGER,
)

register_permission(
    "claims.view",
    label_ar="عرض المطالبات",
    label_en="View claims",
    default_roles={ACCOUNTANT, MANAGER, ADMIN},
)

register_permission(
    "claims.manage",
    label_ar="إنشاء المطالبات وتصديرها",
    label_en="Create and export claims",
    default_roles={ACCOUNTANT, ADMIN},
)

register_permission(
    "claims.record_response",
    label_ar="تسجيل رد جهة التغطية",
    label_en="Record payer responses",
    default_roles={ACCOUNTANT, ADMIN},
)

register_permission(
    "claims.resolve_rejection",
    label_ar="إعادة تحميل المرفوض أو شطبه",
    label_en="Rebill or write off rejected amounts",
    default_roles={ACCOUNTANT, MANAGER, ADMIN},
)

register_permission(
    "claims.record_payer_payment",
    label_ar="تسجيل دفعات جهات التغطية",
    label_en="Record payer payments",
    default_roles={ACCOUNTANT, ADMIN},
)
