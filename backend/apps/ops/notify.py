"""Time-based in-app alerts (FEATURES 0.13), raised by ``manage.py notify_scan``.

Event alerts are raised where things happen (a result approved, stock crossing its minimum,
a rejected transfer, a shift variance). These need a clock instead, so the compose
``maintenance`` loop runs the scan (infra/docker/app-entrypoint.sh):

* ``transfers_pending_overdue``: transfers pending longer than
  ``Policy.pending_transfer_alert_days``, to the verifiers (payments services);
* ``shift_review_pending``: closed shifts no manager has reviewed yet, to the holders of
  ``payments.review_shift``;
* ``stock_low_summary``: items at or below their minimum, to the holders of
  ``pharmacy.receive_goods`` (who reorder);
* ``backup_stale``: no successful backup within ``BACKUP_STALE_HOURS``, to the holders of
  ``ops.view_status``.

Each alert carries a dedupe key with the day, so the scan can run as often as the loop likes
and every recipient gets each alert at most once a day.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone

from apps.core.permissions import roles_holding
from apps.core.services import notify_roles
from apps.ops import services as ops
from apps.payments import services as payments
from apps.payments.models import Shift, ShiftStatus
from apps.pharmacy import services as pharmacy

__all__ = ["scan"]

_LISTED = 20


def _shift_reviews(day: date) -> int:
    pending = list(
        Shift.objects.filter(status=ShiftStatus.CLOSED, review__isnull=True)
        .order_by("closed_at", "id")
        .values("id", "number", "closed_at")
    )
    if not pending:
        return 0
    return notify_roles(
        roles_holding("payments.review_shift"),
        "shift_review_pending",
        dedupe_key=f"shift_review_pending:{day.isoformat()}",
        count=len(pending),
        shifts=[
            {
                "shift_id": s["id"],
                "number": s["number"],
                "closed_at": s["closed_at"].isoformat() if s["closed_at"] else None,
            }
            for s in pending[:_LISTED]
        ],
    )


def _low_stock(day: date) -> int:
    low = pharmacy.low_stock()
    if not low:
        return 0
    return notify_roles(
        roles_holding("pharmacy.receive_goods"),
        "stock_low_summary",
        dedupe_key=f"stock_low_summary:{day.isoformat()}",
        count=len(low),
        items=[
            {
                "item_id": row.item.pk,
                "name": row.item.generic_name,
                "on_hand": row.on_hand,
                "min_stock": row.min_stock,
            }
            for row in low[:_LISTED]
        ],
    )


def _backup(day: date) -> int:
    last = ops.last_backup()
    finished = last.finished_at if last is not None else None
    if finished is not None and timezone.now() - finished <= timedelta(
        hours=ops.BACKUP_STALE_HOURS
    ):
        return 0
    return notify_roles(
        roles_holding("ops.view_status"),
        "backup_stale",
        dedupe_key=f"backup_stale:{day.isoformat()}",
        last_backup_at=finished.isoformat() if finished is not None else None,
        hours=ops.BACKUP_STALE_HOURS,
    )


def scan(*, today: date | None = None) -> dict[str, int]:
    """Raise the time-based alerts due today; returns the notifications created per kind."""
    day = today or timezone.localdate()
    return {
        "transfers_pending_overdue": payments.notify_overdue_transfers(
            today=day, dedupe_key=f"transfers_pending_overdue:{day.isoformat()}"
        ),
        "shift_review_pending": _shift_reviews(day),
        "stock_low_summary": _low_stock(day),
        "backup_stale": _backup(day),
    }
