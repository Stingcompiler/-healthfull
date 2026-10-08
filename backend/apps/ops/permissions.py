"""Permission codes of the ``ops`` app (ARCHITECTURE 4.10). Imported by ``AppConfig.ready``.

``ops.view_status`` is registered with the core codes in ``apps.core.permissions``.
"""

from __future__ import annotations

from apps.core.permissions import register_permission
from apps.core.roles import ADMIN, MANAGER

register_permission(
    "ops.trigger_backup",
    label_ar="تشغيل نسخة احتياطية يدوية",
    label_en="Start a manual backup",
    default_roles={ADMIN},
)

register_permission(
    "ops.manage_updates",
    label_ar="إدارة تحديثات النظام",
    label_en="Manage system updates",
    default_roles={ADMIN},
)

register_permission(
    "ops.export_data",
    label_ar="تصدير البيانات الكامل",
    label_en="Full data export",
    default_roles={ADMIN, MANAGER},
)
