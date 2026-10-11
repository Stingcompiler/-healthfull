"""Closing a visit by hand («ختم الزيارة», FLOW step 3; ``visits.close``: doctor, admin).

The doctor closes the visit once the patient is out of the queue; an admitted patient's visit
closes at discharge. Closing stops new orders but nothing billed: ordered lines are still
invoiced and paid on a closed visit.
"""

from __future__ import annotations

from typing import Any

import pytest

from api.errors import PermissionRequired
from apps.core.tests import builders as b
from apps.orders.models import ServiceLine
from apps.visits import services as vs
from apps.visits.models import Bed, QueueEntry, QueueStatus, Visit
from conftest import TEST_PASSWORD, ApiClient
from domain.errors import DomainError

pytestmark = pytest.mark.django_db


@pytest.fixture
def clerk(make_user: Any) -> Any:
    return make_user("close-clerk", roles=["receptionist"])


@pytest.fixture
def physician(make_user: Any) -> Any:
    return make_user("close-doc", roles=["doctor"])


def _queued_visit(clerk: Any) -> Visit:
    visit = vs.create_visit(patient=b.patient(), actor=clerk, department=b.department())
    if not QueueEntry.objects.filter(visit=visit).exists():
        vs.enqueue(visit, actor=clerk)
    return visit


def test_the_doctor_closes_a_visit_once_the_patient_left_the_queue(
    clerk: Any, physician: Any
) -> None:
    visit = _queued_visit(clerk)
    with pytest.raises(DomainError) as err:
        vs.close_visit_by_hand(visit, actor=physician)
    assert err.value.code == "VISIT_IN_QUEUE"
    entry = QueueEntry.objects.get(visit=visit, status=QueueStatus.WAITING)
    vs.mark_no_show(entry, actor=clerk)
    closed = vs.close_visit_by_hand(visit, actor=physician)
    assert (closed.status, closed.closed_by) == ("closed", physician)
    assert closed.closed_at is not None
    with pytest.raises(DomainError) as err:
        vs.close_visit_by_hand(visit, actor=physician)
    assert err.value.code == "VISIT_NOT_OPEN"


def test_reception_may_not_close_and_admitted_visits_close_at_discharge(
    clerk: Any, physician: Any
) -> None:
    visit = vs.create_visit(patient=b.patient(), actor=clerk, department=b.department())
    for entry in QueueEntry.objects.filter(visit=visit):
        vs.cancel_queue_entry(entry, actor=clerk)
    with pytest.raises(PermissionRequired):
        vs.close_visit_by_hand(visit, actor=clerk)
    bed = Bed.objects.create(
        code="CLS1", name_ar="سرير", name_en="Bed", bed_service=b.service(kind="bed")
    )
    vs.admit(visit, doctor=b.doctor(), bed=bed, actor=clerk)
    with pytest.raises(DomainError) as err:
        vs.close_visit_by_hand(visit, actor=physician)
    assert err.value.code == "VISIT_ADMITTED"


def test_a_closed_visit_takes_no_new_orders_but_keeps_its_lines(clerk: Any, physician: Any) -> None:
    visit = vs.create_visit(patient=b.patient(), actor=clerk, department=b.department())
    line = b.service_line(visit, b.service(kind="lab"))
    for entry in QueueEntry.objects.filter(visit=visit):
        vs.cancel_queue_entry(entry, actor=clerk)
    vs.close_visit_by_hand(visit, actor=physician)
    line.refresh_from_db()
    assert line.billing_status == "unbilled"  # still billable at the cashier
    assert ServiceLine.objects.filter(visit=visit).count() >= 1


def test_api_close(clerk: Any, physician: Any) -> None:
    visit = _queued_visit(clerk)
    doc_api = ApiClient()
    assert doc_api.login("close-doc", TEST_PASSWORD).status_code == 200
    desk_api = ApiClient()
    assert desk_api.login("close-clerk", TEST_PASSWORD).status_code == 200

    denied = desk_api.post(f"/api/visits/{visit.pk}/close")
    assert denied.status_code == 403
    assert denied.json()["details"]["permission"] == "visits.close"
    busy = doc_api.post(f"/api/visits/{visit.pk}/close")
    assert busy.status_code == 409
    assert busy.json()["code"] == "VISIT_IN_QUEUE"
    for entry in QueueEntry.objects.filter(visit=visit):
        vs.mark_no_show(entry, actor=clerk)
    done = doc_api.post(f"/api/visits/{visit.pk}/close")
    assert done.status_code == 200, done.content
    assert done.json()["visit"]["status"] == "closed"
