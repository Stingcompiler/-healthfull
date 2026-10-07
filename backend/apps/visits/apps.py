from __future__ import annotations

from django.apps import AppConfig


class VisitsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.visits"
    label = "visits"
    verbose_name = "Visits"

    def ready(self) -> None:
        # Register this app's permission codes (ARCHITECTURE 4.10).
        from apps.visits import permissions  # noqa: F401
