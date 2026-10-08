"""``/api/orders/perform-first``: documented perform-first exceptions (FEATURES 4.4).

Mounted on the orders router. Every operation needs ``orders.authorize_perform_first``; the
service also checks that the user's role is one of ``Policy.perform_first_roles``. No price
reaches this screen.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from django.http import HttpRequest
from ninja import Field, Query, Router, Schema, Status
from ninja.errors import AuthenticationError

from api.pagination import PageParams
from api.permissions import require_perm
from api.schemas import ERROR_RESPONSES, ErrorOut, Page
from apps.billing.schemas import (
    LineState,
    PatientSummaryOut,
    ReasonOut,
    ServiceRefOut,
    UserRefOut,
    VisitRefOut,
)
from apps.core.models import User
from apps.orders import perform_first

AuthorizationKindCode = Literal["insurance_approval", "emergency", "credit_account", "other"]

perform_first_router = Router()  # tagged "orders" by the parent router

_READ = {**ERROR_RESPONSES, 404: ErrorOut}


class AuthorizableLineOut(Schema):
    id: int
    service: ServiceRefOut
    quantity: int
    state: LineState
    billing_status: str
    fulfilment_status: str
    authorized: bool
    authorizable: bool = Field(..., description="Open and unpaid, with no authorization yet")


class PerformFirstVisitOut(Schema):
    patient: PatientSummaryOut
    visit: VisitRefOut
    lines: list[AuthorizableLineOut]


class AuthorizeIn(Schema):
    line_ids: list[int] = Field(..., min_length=1)
    kind: AuthorizationKindCode = "other"
    reason: str = Field(..., min_length=1, max_length=40)
    note: str = Field("", max_length=1000)
    approval_reference: str = Field("", max_length=100)


class RevokeIn(Schema):
    note: str = Field(..., min_length=1, max_length=1000)


class AuthorizationOut(Schema):
    id: int
    visit_id: int
    visit_number: str
    patient: PatientSummaryOut
    kind: AuthorizationKindCode
    reason: ReasonOut | None
    reason_note: str
    approval_reference: str
    requested_by: UserRefOut | None
    authorized_by: UserRefOut | None
    authorized_at: datetime
    revoked_by: UserRefOut | None
    revoked_at: datetime | None
    revoke_note: str
    lines: list[AuthorizableLineOut]


def _user(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - the router's auth guarantees a User
        raise AuthenticationError()
    return user


@perform_first_router.get(
    "/visits/{visit_id}",
    response={200: PerformFirstVisitOut, **_READ},
    operation_id="orders_get_perform_first_visit",
    summary="A visit's open lines, marking those that may be authorized to go first",
)
@require_perm("orders.authorize_perform_first")
def visit_lines(request: HttpRequest, visit_id: int) -> Any:
    return perform_first.visit_lines(visit_id)


@perform_first_router.post(
    "",
    response={201: AuthorizationOut, **_READ},
    operation_id="orders_authorize_perform_first",
    summary="Authorize open, unpaid lines of one visit to be performed before payment",
)
@require_perm("orders.authorize_perform_first")
def authorize(request: HttpRequest, payload: AuthorizeIn) -> Any:
    return Status(
        201,
        perform_first.authorize(
            payload.line_ids,
            actor=_user(request),
            kind=payload.kind,
            reason=payload.reason,
            note=payload.note,
            approval_reference=payload.approval_reference,
        ),
    )


@perform_first_router.get(
    "",
    response={200: Page[AuthorizationOut], **_READ},
    operation_id="orders_list_perform_first",
    summary="Perform-first authorizations, newest first",
)
@require_perm("orders.authorize_perform_first")
def list_authorizations(
    request: HttpRequest,
    params: Query[PageParams],
    active: bool | None = None,
    visit_id: int | None = None,
) -> Any:
    return perform_first.authorizations(
        active=active,
        visit_id=visit_id,
        q=params.q,
        page=params.page,
        page_size=params.page_size,
    )


@perform_first_router.post(
    "/{authorization_id}/revoke",
    response={200: AuthorizationOut, **_READ},
    operation_id="orders_revoke_perform_first",
    summary="Withdraw an authorization for lines that have not started",
)
@require_perm("orders.authorize_perform_first")
def revoke(request: HttpRequest, authorization_id: int, payload: RevokeIn) -> Any:
    return perform_first.revoke(authorization_id, actor=_user(request), note=payload.note)
