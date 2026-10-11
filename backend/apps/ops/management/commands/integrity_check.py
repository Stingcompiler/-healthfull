"""Check that the books and the stock are consistent (read-only).

    manage.py integrity_check [--json] [--check NAME ...] [--record | --daily]

Checks (``apps.ops.integrity``): ``ledger_balanced`` (trial balance = 0, every entry
balanced), ``invoice_positions`` (AR_PATIENT per invoice = its document position),
``payer_receivables`` (AR_PAYER per payer = claims documents), ``shift_cash`` (CASH per shift =
expected cash, zero once closed), ``stock`` (never negative, balances = sum of moves) and
``allocations`` (no orphan allocations). Exit status 0 when everything matches, 1 otherwise.
Runs in one read-only snapshot; safe while the application is in use, as the app role.
Used by ``infra/backup/restore-drill.sh`` (docs/runbooks/operations.md).

``--record`` stores the result (``ops.IntegrityRun``, shown on the status page) and alerts the
holders of ``ops.view_status`` on findings. ``--daily`` (the compose ``maintenance`` loop, every
cycle) does the same once a local day and exits 0 even on findings: they are reported in the
app, and the loop must not read them as a job to retry (ADR 0021).
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from apps.ops import integrity, integrity_runs


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
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--record", action="store_true", help="store the result and alert on findings"
        )
        mode.add_argument(
            "--daily",
            action="store_true",
            help="once a day: record, alert on findings, exit 0 (maintenance loop)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["daily"]:
            self._daily(options["check"])
            return
        started = timezone.now()
        report = integrity.run(options["check"])
        if options["record"]:
            integrity_runs.record(report, started_at=started, source=integrity_runs.MANUAL)
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

    def _daily(self, only: list[str] | None) -> None:
        if integrity_runs.already_ran_today():
            self.stdout.write("integrity_check: already ran today; skipped")
            return
        run = integrity_runs.run_and_record(source=integrity_runs.SCHEDULED, only=only)
        if run.ok:
            self.stdout.write(f"integrity_check: recorded run {run.pk}: all checks passed")
        else:
            failed = ", ".join(r["name"] for r in run.results if not r["ok"])
            self.stdout.write(
                f"integrity_check: recorded run {run.pk}: FINDINGS in {failed}; "
                "the status page readers were alerted"
            )
