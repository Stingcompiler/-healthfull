"""Service line backstops (ARCHITECTURE 4.4, invariants 1 and 4)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.tests import builders as b
from apps.orders.models import PerformAuthorization, PrescriptionDetail, ServiceLine

pytestmark = pytest.mark.django_db


def _perform(line: ServiceLine) -> None:
    ServiceLine.objects.filter(pk=line.pk).update(
        fulfilment_status="performed", performed_at=timezone.now(), performed_by=b.user()
    )


def _settle(line: ServiceLine) -> None:
    now = timezone.now()
    ServiceLine.objects.filter(pk=line.pk).update(billing_status="invoiced", invoiced_at=now)
    ServiceLine.objects.filter(pk=line.pk).update(billing_status="settled", settled_at=now)


def _authorize(line: ServiceLine) -> PerformAuthorization:
    auth = PerformAuthorization.objects.create(
        visit=line.visit,
        kind="emergency",
        reason_code=b.reason("perform_first"),
        authorized_by=b.user(),
        authorized_at=timezone.now(),
    )
    ServiceLine.objects.filter(pk=line.pk).update(authorization=auth)
    return auth


# --- Invariant 1: no performance without settlement or authorization ------------------------


def test_unpaid_line_cannot_be_performed_orm_or_raw_sql() -> None:
    line = b.service_line()
    b.db_rejects(lambda: _perform(line), "LINE_NOT_ELIGIBLE")
    b.sql_rejects(
        "UPDATE orders_serviceline SET fulfilment_status = 'in_progress', started_at = now() "
        "WHERE id = %s",
        [line.pk],
        "LINE_NOT_ELIGIBLE",
    )
    ServiceLine.objects.filter(pk=line.pk).update(
        billing_status="invoiced", invoiced_at=timezone.now()
    )
    b.db_rejects(lambda: _perform(line), "LINE_NOT_ELIGIBLE")


def test_line_cannot_be_inserted_as_performed() -> None:
    b.db_rejects(
        lambda: b.service_line(
            fulfilment_status="performed", performed_at=timezone.now(), performed_by=b.user()
        ),
        "LINE_NOT_ELIGIBLE",
    )


def test_settled_line_can_be_performed() -> None:
    line = b.service_line()
    _settle(line)
    _perform(line)
    line.refresh_from_db()
    assert line.fulfilment_status == "performed"


def test_authorized_line_can_be_performed_until_revoked() -> None:
    line = b.service_line()
    auth = _authorize(line)
    ServiceLine.objects.filter(pk=line.pk).update(
        fulfilment_status="in_progress", started_at=timezone.now()
    )
    PerformAuthorization.objects.filter(pk=auth.pk).update(
        revoked_at=timezone.now(), revoked_by=b.user()
    )
    b.db_rejects(lambda: _perform(line), "LINE_NOT_ELIGIBLE")


def test_terminal_fulfilment_never_changes() -> None:
    line = b.service_line()
    _settle(line)
    _perform(line)
    b.db_rejects(
        lambda: ServiceLine.objects.filter(pk=line.pk).update(fulfilment_status="pending"),
        "LINE_TERMINAL",
    )
    cancelled = b.service_line()
    ServiceLine.objects.filter(pk=cancelled.pk).update(
        fulfilment_status="cancelled",
        cancelled_at=timezone.now(),
        cancelled_by=b.user(),
        cancel_reason=b.reason("line_cancel"),
    )
    b.sql_rejects(
        "UPDATE orders_serviceline SET fulfilment_status = 'pending' WHERE id = %s",
        [cancelled.pk],
        "LINE_TERMINAL",
    )


def test_a_performed_line_may_still_be_credited() -> None:
    line = b.service_line()
    _settle(line)
    _perform(line)
    ServiceLine.objects.filter(pk=line.pk).update(
        billing_status="credited", credited_at=timezone.now()
    )


@pytest.mark.parametrize(
    ("start", "target"),
    [("unbilled", "credited"), ("credited", "invoiced"), ("credited", "settled")],
)
def test_billing_moves_only_along_the_state_machine(start: str, target: str) -> None:
    line = b.service_line()
    now = timezone.now()
    if start != "unbilled":
        ServiceLine.objects.filter(pk=line.pk).update(billing_status="invoiced", invoiced_at=now)
        ServiceLine.objects.filter(pk=line.pk).update(billing_status=start, credited_at=now)
    b.db_rejects(
        lambda: ServiceLine.objects.filter(pk=line.pk).update(
            billing_status=target, invoiced_at=now, credited_at=now
        ),
        "LINE_BILLING_TRANSITION",
    )


def test_settled_line_may_fall_back_to_invoiced() -> None:
    line = b.service_line()
    _settle(line)
    ServiceLine.objects.filter(pk=line.pk).update(billing_status="invoiced")


def test_lines_are_never_deleted() -> None:
    line = b.service_line()
    b.db_rejects(lambda: ServiceLine.objects.filter(pk=line.pk).delete(), "LINE_NOT_DELETABLE")
    b.sql_rejects("DELETE FROM orders_serviceline WHERE id = %s", [line.pk], "LINE_NOT_DELETABLE")


# --- Invariant 4 and shape constraints -------------------------------------------------------


def test_cancellation_records_reason_actor_and_time() -> None:
    line = b.service_line()
    b.db_rejects(
        lambda: ServiceLine.objects.filter(pk=line.pk).update(
            fulfilment_status="cancelled", cancelled_at=timezone.now(), cancelled_by=b.user()
        ),
        "orders_line_cancel_documented",
    )


def test_performance_records_actor_and_time() -> None:
    line = b.service_line()
    _settle(line)
    b.db_rejects(
        lambda: ServiceLine.objects.filter(pk=line.pk).update(fulfilment_status="performed"),
        "orders_line_performed_documented",
    )


def test_quantities() -> None:
    with pytest.raises(IntegrityError, match="orders_line_qty_positive"), transaction.atomic():
        b.service_line(quantity=Decimal("0"))
    line = b.service_line(quantity=Decimal("10"))
    b.db_rejects(
        lambda: ServiceLine.objects.filter(pk=line.pk).update(performed_quantity=Decimal("11")),
        "orders_line_performed_qty_range",
    )


def test_invoiced_line_has_timestamp() -> None:
    line = b.service_line()
    b.db_rejects(
        lambda: ServiceLine.objects.filter(pk=line.pk).update(billing_status="invoiced"),
        "orders_line_invoiced_has_time",
    )


def test_authorization_needs_reason_and_revocation_actor() -> None:
    line = b.service_line()
    with pytest.raises(IntegrityError), transaction.atomic():
        PerformAuthorization.objects.create(
            visit=line.visit,
            kind="emergency",
            authorized_by=b.user(),
            authorized_at=timezone.now(),
        )
    auth = _authorize(line)
    b.db_rejects(
        lambda: PerformAuthorization.objects.filter(pk=auth.pk).update(revoked_at=timezone.now()),
        "orders_authorization_revoke_documented",
    )


def test_prescription_detail() -> None:
    line = b.service_line(svc=b.service(kind="drug"))
    detail = PrescriptionDetail.objects.create(
        line=line, dose="500 mg", frequency_code="TID", frequency_per_day=Decimal("3")
    )
    assert line.prescription == detail
    assert str(detail) == "500 mg TID"
    with (
        pytest.raises(IntegrityError, match="orders_prescription_route_valid"),
        transaction.atomic(),
    ):
        PrescriptionDetail.objects.create(
            line=b.service_line(svc=b.service(kind="drug")), dose="1", route="telepathic"
        )
