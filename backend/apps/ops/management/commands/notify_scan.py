"""Time-based in-app alerts (FEATURES 0.13): overdue transfers, shifts awaiting review, low
stock and a stale backup.

    manage.py notify_scan

Idempotent within a day (each alert has a per-day dedupe key), so the compose
``maintenance`` loop may run it as often as it runs. See ``apps.ops.notify``.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.ops.notify import scan


class Command(BaseCommand):
    help = "Raise the time-based in-app alerts due today (idempotent within a day)."

    def handle(self, *args: Any, **options: Any) -> None:
        created = scan()
        summary = ", ".join(f"{kind} {count}" for kind, count in created.items())
        self.stdout.write(f"notify_scan: {summary}.")
