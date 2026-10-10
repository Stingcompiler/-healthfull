"""Check that the books and the stock are consistent (read-only).

    manage.py integrity_check [--json] [--check NAME ...]

Checks (``apps.ops.integrity``): ``ledger_balanced`` (trial balance = 0, every entry
balanced), ``invoice_positions`` (AR_PATIENT per invoice = its document position),
``payer_receivables`` (AR_PAYER per payer = claims documents), ``shift_cash`` (CASH per shift =
expected cash, zero once closed), ``stock`` (never negative, balances = sum of moves) and
``allocations`` (no orphan allocations). Exit status 0 when everything matches, 1 otherwise.
Runs in one read-only snapshot; safe while the application is in use, as the app role.
Used by ``infra/backup/restore-drill.sh`` (docs/runbooks/operations.md).
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.ops import integrity


class Command(BaseCommand):
    help = "Check ledger balance, document positions, stock and allocations (read-only)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--json", action="store_true", help="print one JSON object")
        parser.add_argument(
            "--check",
            action="append",
            choices=sorted(integrity.CHECKS),
            help="run only this check (repeatable)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        report = integrity.run(options["check"])
        if options["json"]:
            self.stdout.write(json.dumps(report.to_json(), ensure_ascii=False, sort_keys=True))
        else:
            for r in report.results:
                state = "ok" if r.ok else f"FAILED ({r.count} problem(s))"
                self.stdout.write(f"{r.name}: {state}; {r.checked} checked")
                for problem in r.problems:
                    self.stdout.write(f"  - {problem}")
                if r.count > len(r.problems):
                    self.stdout.write(f"  ... and {r.count - len(r.problems)} more")
        if not report.ok:
            failed = [r.name for r in report.results if not r.ok]
            raise CommandError(f"integrity check failed: {', '.join(failed)}")
        if not options["json"]:
            self.stdout.write(f"integrity_check: {report.database}: all checks passed")
