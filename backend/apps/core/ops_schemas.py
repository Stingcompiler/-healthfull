"""Schemas of ``/api/core/notifications`` and ``/api/core/audit`` (ARCHITECTURE 4.11)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from ninja import Field, Schema

from api.pagination import PageParams
from apps.patients.schemas import UserRefOut


class NotificationOut(Schema):
    id: int
    kind: str = Field(
        ...,
        description=(
            "lab_result_ready, lab_result_critical, stock_low, stock_low_summary, "
            "transfers_pending_overdue, transfer_rejected, patient_credit_negative, "
            "shift_variance, shift_review_pending"
        ),
    )
    payload: dict[str, Any] = Field(..., description="Ids, numbers and amounts of the alert")
    created_at: datetime
    read_at: datetime | None


class NotificationListParams(PageParams):
    unread: bool = Field(False, description="Only the unread notifications")


class UnreadCountOut(Schema):
    count: int


class MarkAllReadOut(Schema):
    updated: int


AuditAction = Literal["insert", "update", "delete"]


class AuditModelOut(Schema):
    label: str = Field(..., description="app_label.ModelName, e.g. billing.Invoice")
    app_label: str
    verbose_name: str


class AuditChangeOut(Schema):
    field: str
    before: Any = None
    after: Any = None


class AuditEventOut(Schema):
    id: str
    model: str
    model_name: str
    object_id: str | None
    action: str
    created_at: datetime
    user: UserRefOut | None
    user_id: int | None
    reason: str
    method: str
    url: str
    request_id: str
    changes: list[AuditChangeOut]


class AuditParams(PageParams):
    model: str | None = Field(None, max_length=100, description="app_label.ModelName")
    user_id: int | None = Field(None, ge=1)
    date_from: date | None = None
    date_to: date | None = None
    object_id: str | None = Field(None, max_length=64)
    action: AuditAction | None = None
