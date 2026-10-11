"""Recorded integrity checks: the daily run of the maintenance loop and its alert (ADR 0021).

``manage.py integrity_check --daily`` (compose ``maintenance`` loop, every cycle) runs the six
read-only checks of ``apps.ops.integrity`` once a local day, records the result in
``IntegrityRun`` and, when anything does not match, alerts the holders of ``ops.view_status``
(administrators and managers by default) with ``integrity_failed``, linking to the status
page, which shows the newest run. ``--record`` records a run by hand. A finding is reported,
never repaired (runbook: back up and call support).
"""

from __future__ import annotations

from datetime import date, datetime

from django.utils import timezone

from apps.core.services import notify_kind
from apps.ops import integrity
from apps.ops.models import IntegrityRun

__all__ = ["already_ran_today", "last_run", "record", "run_and_record"]

SCHEDULED = "scheduled"
MANUAL = "manual"


def last_run() -> IntegrityRun | None:
    return IntegrityRun.objects.order_by("-started_at", "-id").first()


def already_ran_today(today: date | None = None) -> bool:
    """Whether a scheduled run already started on ``today`` (local date)."""
    day = today or timezone.localdate()
    return any(
        timezone.localdate(started) == day
        for started in IntegrityRun.objects.filter(source=SCHEDULED)
        .order_by("-started_at")
        .values_list("started_at", flat=True)[:5]
    )


def record(
    report: integrity.IntegrityReport,
    *,
    started_at: datetime,
    source: str = SCHEDULED,
    finished_at: datetime | None = None,
) -> IntegrityRun:
    """Store one run and, when a check failed, alert the status page's readers once a day."""
    run = IntegrityRun.objects.create(
        started_at=started_at,
        finished_at=finished_at or timezone.now(),
        ok=report.ok,
        source=source,
        database=report.database[:100],
        results=[
            {
                "name": r.name,
                "ok": r.ok,
                "checked": r.checked,
                "problems": r.count,
                "examples": list(r.problems),
            }
            for r in report.results
        ],
    )
    if not report.ok:
        failed = [r.name for r in report.results if not r.ok]
        notify_kind(
            "integrity_failed",
            dedupe_key=f"integrity_failed:{timezone.localdate(run.started_at).isoformat()}",
            run_id=run.pk,
            failed=failed,
            count=len(failed),
        )
    return run


def run_and_record(*, source: str = SCHEDULED, only: list[str] | None = None) -> IntegrityRun:
    started = timezone.now()
    report = integrity.run(only)
    return record(report, started_at=started, source=source)
