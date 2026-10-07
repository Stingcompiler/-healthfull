from __future__ import annotations

from django.apps import AppConfig


class ImportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.imports"
    label = "imports"
    verbose_name = "Imports"

    def ready(self) -> None:
        # Register this app's permission codes (ARCHITECTURE 4.10).
        from apps.imports import permissions  # noqa: F401
