"""e2e builders of the system pages (``manage.py e2e_fixture``, test databases only).

``ops_import_sheet``: an .xlsx import sheet (base64) of a kind with the template's English
header row and the given rows, so a spec can upload a real Excel file (the e2e package has no
spreadsheet library). Nothing is written to the database.

``ops_notifications``: marks a user's notifications read, then gives them fresh ones through
``notify_users`` (a low-stock summary, shifts awaiting review, a stale backup), so the bell
shows a known unread count whatever ran before.

``ops_reset_backup_requests``: finishes every open manual backup request as failed, as the
backup service does with an interrupted one, so a spec can ask for a backup again (there is
no backup service in the e2e stack).
"""

from __future__ import annotations

import base64
import io

from django.utils import timezone

from apps.core.e2e.fixtures import Json, Params, fixture
from apps.core.models import Notification, User
from apps.core.services import notify_users
from apps.imports import services as imports
from apps.ops.models import OPEN_BACKUP_REQUESTS, BackupRequest
from domain import item_import, patient_import, price_import
from domain.errors import DomainError

_HEADERS = {
    "patients": [c.label_en for c in patient_import.COLUMNS],
    "items": [c.label_en for c in item_import.COLUMNS],
    "prices": [c.label_en for c in price_import.COLUMNS],
}


@fixture(
    "ops_import_sheet",
    summary=(
        "An .xlsx sheet of `kind` (patients, items, prices) with the template's English "
        "header (or `header`) and `rows` (lists of cell values; dates as YYYY-MM-DD). "
        "Returns filename and base64."
    ),
    params=("kind", "rows", "header"),
)
def ops_import_sheet(p: Params) -> Json:
    from openpyxl import Workbook

    kind = p.text("kind", "patients")
    if kind not in _HEADERS:
        raise DomainError("IMPORT_KIND_UNKNOWN", "Unknown import kind", kind=kind)
    header = p.items("header") or _HEADERS[kind]
    book = Workbook()
    sheet = book.active or book.create_sheet()
    sheet.append([str(h) for h in header])
    for row in p.items("rows"):
        if not isinstance(row, list):
            raise DomainError(
                "FIXTURE_PARAM_INVALID", "rows: expected lists of cells", param="rows"
            )
        sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    content = out.getvalue()
    if len(content) > imports.MAX_FILE_BYTES:
        raise DomainError("IMPORT_FILE_TOO_LARGE", "The sheet is larger than an upload may be")
    return {
        "filename": f"{kind}-e2e.xlsx",
        "base64": base64.b64encode(content).decode("ascii"),
    }


@fixture(
    "ops_notifications",
    summary=(
        "Marks `user`'s (default manager) notifications read, then adds three unread ones "
        "(stock_low_summary, shift_review_pending, backup_stale). Returns user and unread."
    ),
    params=("user",),
)
def ops_notifications(p: Params) -> Json:
    username = p.text("user", "manager")
    user = User.objects.filter(username=username, is_active=True).first()
    if user is None:
        raise DomainError("FIXTURE_REF_NOT_FOUND", f"No user {username!r}", kind="user")
    Notification.objects.filter(user=user, read_at__isnull=True).update(read_at=timezone.now())
    notify_users(
        [user],
        "stock_low_summary",
        count=2,
        items=[{"item_id": 0, "name": "Ceftriaxone", "on_hand": 8, "min_stock": 20}],
    )
    notify_users([user], "shift_review_pending", count=1, shifts=[])
    notify_users([user], "backup_stale", hours=36, last_backup_at=None)
    unread = Notification.objects.filter(user=user, read_at__isnull=True).count()
    return {"user": user.username, "unread": unread}


@fixture(
    "ops_reset_backup_requests",
    summary="Finishes every open manual backup request as failed (no backup service in e2e).",
    params=(),
)
def ops_reset_backup_requests(p: Params) -> Json:
    count = BackupRequest.objects.filter(status__in=OPEN_BACKUP_REQUESTS).update(
        status="failed",
        finished_at=timezone.now(),
        message="Closed by the e2e fixture: there is no backup service in the test stack.",
    )
    return {"closed": count}
