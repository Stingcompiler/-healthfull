"""Record one run of ``infra/update.sh`` in ``ops.UpdateRun`` (FEATURES 13.10).

    manage.py record_update --run-key 20261010T120000Z-v1.4.0 --to v1.4.0 --from v1.3.2 \\
        --result rolled_back --started-at 2026-10-10T12:00:00Z --finished-at ... \\
        [--migrations-applied] [--db-restored] [--backup /backups/dumps/x.dump] \\
        [--detail "why"] [--stdin]

The update script calls it once at the end of every run (success, failure or rollback), in a
one-off container of the version that is serving at that moment, and once for a run that a
power cut interrupted (``--result failed``). It writes through ``apps.ops.services``, never
raw SQL. ``--run-key`` makes a repeated call update the same row.

With ``--stdin`` the long texts arrive on standard input in sections, each starting with a
header line of its own: ``@@plan`` (``migrate --plan`` output), ``@@notes`` (release notes)
and ``@@log`` (the tail of the update log). Lines before the first header are ignored.
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.ops.services import SCRIPT_RESULTS, UpdateRecord, record_update_run

SECTIONS = {"@@plan": "plan", "@@notes": "notes", "@@log": "log"}


def parse_sections(text: str) -> dict[str, str]:
    """Split the ``--stdin`` text into its ``@@plan`` / ``@@notes`` / ``@@log`` sections."""
    parts: dict[str, list[str]] = {name: [] for name in SECTIONS.values()}
    current: str | None = None
    for line in text.splitlines():
        header = SECTIONS.get(line.strip())
        if header is not None:
            current = header
            continue
        if current is not None:
            parts[current].append(line)
    return {name: "\n".join(lines).strip("\n") for name, lines in parts.items()}


def _moment(value: str | None, option: str) -> datetime | None:
    if value is None or value == "":
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        raise CommandError(f"{option}: not an ISO 8601 date and time: {value!r}")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_fixed_timezone(0))
    return parsed


class Command(BaseCommand):
    help = "Record one run of infra/update.sh in the update history (ops.UpdateRun)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--run-key", required=True, help="the script's run id")
        parser.add_argument("--to", required=True, dest="version", help="target image tag")
        parser.add_argument("--from", default="", dest="previous", help="previous image tag")
        parser.add_argument("--result", required=True, choices=sorted(SCRIPT_RESULTS))
        parser.add_argument("--started-at", required=True)
        parser.add_argument("--finished-at", default=None)
        parser.add_argument("--migrations-applied", action="store_true")
        parser.add_argument("--db-restored", action="store_true")
        parser.add_argument("--backup", default="", help="the pre-update dump")
        parser.add_argument("--detail", default="", help="why it failed or rolled back")
        parser.add_argument(
            "--stdin", action="store_true", help="read @@plan / @@notes / @@log sections"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        started = _moment(options["started_at"], "--started-at")
        if started is None:
            raise CommandError("--started-at is required")
        sections = parse_sections(sys.stdin.read()) if options["stdin"] else {}
        record = UpdateRecord(
            run_key=options["run_key"],
            version=options["version"],
            previous_version=options["previous"],
            result=options["result"],
            started_at=started,
            finished_at=_moment(options["finished_at"], "--finished-at"),
            migration_plan=sections.get("plan", ""),
            migrations_applied=options["migrations_applied"],
            db_restored=options["db_restored"],
            backup_file=options["backup"],
            detail=options["detail"],
            log=sections.get("log", ""),
            release_notes=sections.get("notes", ""),
        )
        try:
            run = record_update_run(record)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"record_update: update run {run.pk} {run.version} {run.result}")
