from __future__ import annotations

from django.apps import AppConfig


class PharmacyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pharmacy"
    label = "pharmacy"
    verbose_name = "Pharmacy"

    def ready(self) -> None:
        # Register this app's permission codes (ARCHITECTURE 4.10).
        from apps.pharmacy import permissions  # noqa: F401
