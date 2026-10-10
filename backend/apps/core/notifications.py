"""The signed-in user's in-app notifications (FEATURES 0.13).

Notifications are created by the modules where things happen (``notify_users`` /
``notify_roles``: a lab result approved, stock crossing its minimum, a rejected transfer, a
shift variance) and by the daily ``manage.py notify_scan`` for time-based alerts. Each
user only ever reads and marks their own.
"""

from __future__ import annotations

from django.db.models import QuerySet
from django.utils import timezone

from apps.core.models import Notification, User

__all__ = ["mark_all_read", "mark_read", "unread_count", "user_notifications"]


def user_notifications(user: User, *, unread_only: bool = False) -> QuerySet[Notification]:
    """``user``'s notifications, newest first."""
    rows = Notification.objects.filter(user=user)
    if unread_only:
        rows = rows.filter(read_at__isnull=True)
    return rows.order_by("-created_at", "-id")


def unread_count(user: User) -> int:
    return Notification.objects.filter(user=user, read_at__isnull=True).count()


def mark_read(user: User, notification_id: int) -> Notification:
    """Mark one of ``user``'s notifications read (idempotent).

    Raises:
        Notification.DoesNotExist: not one of ``user``'s notifications (HTTP 404).
    """
    note = Notification.objects.get(pk=notification_id, user=user)
    if note.read_at is None:
        note.read_at = timezone.now()
        note.save(update_fields=["read_at"])
    return note


def mark_all_read(user: User) -> int:
    """Mark every unread notification of ``user`` read; returns how many changed."""
    return Notification.objects.filter(user=user, read_at__isnull=True).update(
        read_at=timezone.now()
    )
