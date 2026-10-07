from __future__ import annotations

from django.apps import AppConfig


class PatientsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.patients"
    label = "patients"
    verbose_name = "Patients"

    def ready(self) -> None:
        # Register this app's permission codes (ARCHITECTURE 4.10).
        from apps.patients import permissions  # noqa: F401
