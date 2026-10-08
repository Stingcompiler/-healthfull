from __future__ import annotations

from django.apps import AppConfig


class OrdersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.orders"
    label = "orders"
    verbose_name = "Orders"

    def ready(self) -> None:
        # Register this app's permission codes (ARCHITECTURE 4.10).
        from apps.orders import permissions  # noqa: F401
