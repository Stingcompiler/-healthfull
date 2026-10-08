from __future__ import annotations

from django.apps import AppConfig


class LabConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.lab"
    label = "lab"
    verbose_name = "Laboratory"

    def ready(self) -> None:
        # Register this app's permission codes (ARCHITECTURE 4.10).
        from apps.lab import permissions  # noqa: F401
