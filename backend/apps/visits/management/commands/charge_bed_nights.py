"""Daily bed charge run (FEATURES 10.5): add every open admission's passed nights.

    manage.py charge_bed_nights --as <username>

Idempotent (a night is charged once), so it is safe to run more than once a day or after a
missed day. The acting user is recorded on the lines and in the audit trail and must hold
``visits.manage_beds``. The bed board's "post due nights" button does the same.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from api.errors import PermissionRequired
from apps.core.models import User
from apps.core.services import require_permission
from apps.visits import services


class Command(BaseCommand):
    help = "Charge every open admission's passed bed nights (idempotent)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--as", dest="username", required=True, help="Acting username")

    def handle(self, *args: Any, **options: Any) -> None:
        user = User.objects.filter(username=options["username"], is_active=True).first()
        if user is None:
            raise CommandError(f"No active user {options['username']!r}")
        try:
            require_permission(user, "visits.manage_beds")
        except PermissionRequired as exc:
            raise CommandError(f"{user.username} may not manage beds") from exc
        created = services.charge_due_bed_nights(actor=user)
        admissions = len({c.admission_id for c in created})
        self.stdout.write(
            f"charge_bed_nights: {len(created)} night(s) charged on {admissions} admission(s)."
        )
