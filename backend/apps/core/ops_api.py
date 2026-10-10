"""``/api/core/notifications`` and ``/api/core/audit`` (FEATURES 0.13, 0.4).

* Notifications: the signed-in user's own (list, unread count, mark read, mark all read).
  Every signed-in user has them, so these carry no permission code; each query is scoped to
  ``request.user`` and another user's notification is a 404.
* Audit: the pghistory trail of every tracked model, for holders of ``core.view_audit``.

Mounted on the core router; each operation calls one function of ``apps.core.notifications``
or ``apps.core.audit``.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from ninja import Query, Router

from api.errors import PermissionRequired
from api.pagination import paginate
from api.permissions import require_perm
from api.schemas import ERROR_RESPONSES, ErrorOut, Page
from apps.core import audit, notifications
from apps.core.models import Notification, User
from apps.core.ops_schemas import (
    AuditEventOut,
    AuditModelOut,
    AuditParams,
    MarkAllReadOut,
    NotificationListParams,
    NotificationOut,
    UnreadCountOut,
)

notifications_router = Router()  # tagged "core" by the parent router
audit_router = Router()

_READ = {401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut}
_WRITE = {**ERROR_RESPONSES, 404: ErrorOut}


def _user(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - session auth guarantees a User
        raise PermissionRequired("core.view_audit")
    return user


@notifications_router.get(
    "",
    response={200: Page[NotificationOut], **_READ},
    operation_id="core_list_notifications",
    summary="The signed-in user's notifications, newest first",
)
def list_notifications(
    request: HttpRequest, params: Query[NotificationListParams]
) -> dict[str, Any]:
    rows = notifications.user_notifications(_user(request), unread_only=params.unread)
    return paginate(rows, params.page, params.page_size)


@notifications_router.get(
    "/unread-count",
    response={200: UnreadCountOut, **_READ},
    operation_id="core_get_unread_notification_count",
    summary="How many of the signed-in user's notifications are unread (the bell badge)",
)
def unread_count(request: HttpRequest) -> dict[str, int]:
    return {"count": notifications.unread_count(_user(request))}


@notifications_router.post(
    "/{int:notification_id}/read",
    response={200: NotificationOut, **_WRITE},
    operation_id="core_mark_notification_read",
    summary="Mark one of the signed-in user's notifications read",
)
def mark_read(request: HttpRequest, notification_id: int) -> Notification:
    return notifications.mark_read(_user(request), notification_id)


@notifications_router.post(
    "/read-all",
    response={200: MarkAllReadOut, **_WRITE},
    operation_id="core_mark_all_notifications_read",
    summary="Mark every notification of the signed-in user read",
)
def mark_all_read(request: HttpRequest) -> dict[str, int]:
    return {"updated": notifications.mark_all_read(_user(request))}


@audit_router.get(
    "/models",
    response={200: list[AuditModelOut], **_READ},
    operation_id="core_list_audit_models",
    summary="The models with an audit trail (the viewer's model filter)",
)
@require_perm("core.view_audit")
def list_audit_models(request: HttpRequest) -> list[audit.AuditModel]:
    return audit.audit_models()


@audit_router.get(
    "/events",
    response={200: Page[AuditEventOut], **_READ, 409: ErrorOut},
    operation_id="core_list_audit_events",
    summary="Audit events (who, when, what changed, why), newest first, filtered",
    description=(
        "Filters: model (app_label.ModelName), user_id, date_from/date_to (inclusive days), "
        "object_id, action (insert, update, delete). Secret fields are shown as ***. "
        "409 AUDIT_MODEL_UNKNOWN, AUDIT_ACTION_UNKNOWN, INVALID_DATE_RANGE."
    ),
)
@require_perm("core.view_audit")
def list_audit_events(request: HttpRequest, params: Query[AuditParams]) -> dict[str, Any]:
    filters = audit.AuditFilters(
        model=params.model or None,
        user_id=params.user_id,
        date_from=params.date_from,
        date_to=params.date_to,
        object_id=(params.object_id or "").strip() or None,
        action=params.action,
    )
    return audit.audit_events(filters, page=params.page, page_size=params.page_size)
