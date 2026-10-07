from __future__ import annotations

from django.apps import AppConfig


class ClaimsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.claims"
    label = "claims"
    verbose_name = "Claims"

    def ready(self) -> None:
        # Register this app's permission codes (ARCHITECTURE 4.10).
        from apps.claims import permissions  # noqa: F401
