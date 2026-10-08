"""Permission codes of the ``imports`` app (ARCHITECTURE 4.10). Imported by ``AppConfig.ready``.

Defaults follow FLOW.md roles; ``admin`` holds every code; doctors never hold billing codes.
``RolePermission`` rows override these defaults per role.
"""

from __future__ import annotations

from apps.core.permissions import register_permission
from apps.core.roles import (
    ADMIN,
)

register_permission(
    "imports.run",
    label_ar="استيراد بيانات Excel",
    label_en="Run Excel imports",
    default_roles={ADMIN},
)
