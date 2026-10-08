"""The perform-first authorization screen (FEATURES 4.4, invariant 1).

Reads the open lines of a visit a supervisor may authorize, records an authorization through
``apps.orders.services.authorize_perform_first`` (which checks the role, the reason and the
lines) and lists or revokes authorizations. Returns plain dicts shaped like
``apps.orders.perform_first_api``; no prices are read or returned.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.db.models import Prefetch, Q, QuerySet

from api.pagination import paginate
from apps.billing import queries as bq
from apps.core.models import User
from apps.orders import services as orders
from apps.orders.models import FulfilmentStatus, PerformAuthorization, ServiceLine
from apps.visits.models import Visit
from domain import service_line as dsl

__all__ = ["authorizations", "authorize", "requesters", "revoke", "visit_lines"]

_OPEN = (FulfilmentStatus.PENDING, FulfilmentStatus.IN_PROGRESS)


def _line_json(sl: ServiceLine) -> dict[str, Any]:
    status = orders.line_status(sl)
    return {
        "id": sl.pk,
        "service": bq.service_json(sl.service),
        "quantity": orders.whole_quantity(sl.quantity),
        "state": str(orders.line_state(sl)),
        "billing_status": sl.billing_status,
        "fulfilment_status": sl.fulfilment_status,
        "authorized": status.authorized,
        "authorizable": dsl.can_authorize(status),
    }


def visit_lines(visit_id: int) -> dict[str, Any]:
    """The visit's open lines: the unpaid ones can be authorized to go first."""
    visit = Visit.objects.select_related("patient", "department", "doctor__user", "payer").get(
        pk=visit_id
    )
    lines = (
        ServiceLine.objects.filter(visit=visit, fulfilment_status__in=_OPEN)
        .select_related("service", "authorization")
        .order_by("id")
    )
    return {
        "patient": bq.patient_json(visit.patient),
        "visit": bq.visit_ref_json(visit),
        "lines": [_line_json(sl) for sl in lines],
    }


def _auth_json(auth: PerformAuthorization) -> dict[str, Any]:
    return {
        "id": auth.pk,
        "visit_id": auth.visit_id,
        "visit_number": auth.visit.number,
        "patient": bq.patient_json(auth.visit.patient),
        "kind": auth.kind,
        "reason": bq.reason_json(auth.reason_code),
        "reason_note": auth.reason_note,
        "approval_reference": auth.approval_reference,
        "requested_by": bq.user_json(auth.requested_by),
        "authorized_by": bq.user_json(auth.authorized_by),
        "authorized_at": auth.authorized_at,
        "revoked_by": bq.user_json(auth.revoked_by),
        "revoked_at": auth.revoked_at,
        "revoke_note": auth.revoke_note,
        "lines": [_line_json(sl) for sl in auth.lines.all()],
    }


def _auths() -> QuerySet[PerformAuthorization]:
    return PerformAuthorization.objects.select_related(
        "visit__patient", "reason_code", "requested_by", "authorized_by", "revoked_by"
    ).prefetch_related(
        Prefetch(
            "lines",
            queryset=ServiceLine.objects.select_related("service", "authorization").order_by("id"),
        )
    )


def authorize(
    line_ids: Sequence[int],
    *,
    actor: User,
    kind: str,
    reason: str,
    note: str,
    approval_reference: str,
    requested_by_id: int | None = None,
) -> dict[str, Any]:
    """Allow open, unpaid lines of one visit to be performed before payment.

    ``requested_by_id`` names the active user who asked for the exception (the doctor or the
    lab, FEATURES 4.4 "who"); without it the authorizer is recorded as the requester.
    """
    lines = list(ServiceLine.objects.filter(pk__in=list(line_ids)).order_by("id"))
    if len(lines) != len(set(line_ids)):
        raise ServiceLine.DoesNotExist("service line")
    requester = (
        User.objects.get(pk=requested_by_id, is_active=True)
        if requested_by_id is not None
        else None
    )
    auth = orders.authorize_perform_first(
        lines,
        actor=actor,
        reason=reason,
        kind=kind,
        note=note,
        approval_reference=approval_reference,
        requested_by=requester,
    )
    return _auth_json(_auths().get(pk=auth.pk))


def requesters(q: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
    """Active staff who may have asked for a perform-first exception, by username."""
    qs = User.objects.filter(is_active=True)
    if q and q.strip():
        term = q.strip()
        qs = qs.filter(
            Q(username__icontains=term)
            | Q(full_name_ar__icontains=term)
            | Q(full_name_en__icontains=term)
        )
    users = qs.order_by("username")[:limit]
    return [u for u in (bq.user_json(user) for user in users) if u is not None]


def revoke(authorization_id: int, *, actor: User, note: str) -> dict[str, Any]:
    """Withdraw an authorization for lines that have not started."""
    orders.revoke_authorization(
        PerformAuthorization.objects.get(pk=authorization_id), actor=actor, note=note
    )
    return _auth_json(_auths().get(pk=authorization_id))


def authorizations(
    *,
    active: bool | None = None,
    visit_id: int | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """Authorizations, newest first (the performed-by-authorization trail, FEATURES 4.5)."""
    qs = _auths().order_by("-authorized_at", "-id")
    if active is not None:
        qs = qs.filter(revoked_at__isnull=active)
    if visit_id is not None:
        qs = qs.filter(visit_id=visit_id)
    if q:
        term = q.strip()
        qs = qs.filter(Q(visit__number__iexact=term) | Q(visit__patient__file_no__iexact=term))
    data = paginate(qs, page, page_size)
    data["items"] = [_auth_json(a) for a in data["items"]]
    return data
