from __future__ import annotations

from django.apps import AppConfig


class LedgerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ledger"
    label = "ledger"
    verbose_name = "Ledger"
    # No permission codes: the ledger has no endpoint or screen. Its figures reach people
    # through the reports and `manage.py integrity_check`; `ledger.view` and
    # `ledger.manage_accounts` were never used and were removed (core migration 0016).
