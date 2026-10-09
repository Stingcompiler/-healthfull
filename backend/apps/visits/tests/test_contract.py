"""Route contract of ``/api/visits``: pinned operation ids, and every operation refuses a
signed-in user without the permission with 403 before reading the request (no 422)."""

from __future__ import annotations

from typing import Any

import pytest

from apps.patients.tests.test_contract import assert_role_less_user_is_refused, module_operations
from conftest import ApiClient

pytestmark = pytest.mark.django_db

PREFIX = "/api/visits"

#: The module's operations; a removed or renamed route fails here.
OPERATIONS = {
    ("get", "/api/visits/options"): "visits_get_options",
    ("get", "/api/visits"): "visits_list_visits",
    ("post", "/api/visits"): "visits_create_visit",
    ("get", "/api/visits/{visit_id}"): "visits_get_visit",
    ("post", "/api/visits/{visit_id}/cancel"): "visits_cancel_visit",
    ("get", "/api/visits/{visit_id}/timeline"): "visits_get_timeline",
    ("get", "/api/visits/queue/board"): "visits_get_board",
    ("post", "/api/visits/queue/call-next"): "visits_call_next",
    ("post", "/api/visits/queue/{entry_id}/move"): "visits_move_queue_entry",
    ("get", "/api/visits/queue/display"): "visits_get_display",
    ("get", "/api/visits/queue/{entry_id}/token"): "visits_get_token_slip",
    ("get", "/api/visits/appointments/day"): "visits_get_agenda",
    ("get", "/api/visits/appointments/upcoming"): "visits_list_upcoming_appointments",
    ("post", "/api/visits/appointments"): "visits_book_appointment",
    ("patch", "/api/visits/appointments/{appointment_id}"): "visits_update_appointment",
    (
        "post",
        "/api/visits/appointments/{appointment_id}/reschedule",
    ): "visits_reschedule_appointment",
    ("post", "/api/visits/appointments/{appointment_id}/cancel"): "visits_cancel_appointment",
    (
        "post",
        "/api/visits/appointments/{appointment_id}/no-show",
    ): "visits_mark_appointment_no_show",
    ("post", "/api/visits/appointments/{appointment_id}/check-in"): "visits_check_in_appointment",
    ("get", "/api/visits/ping"): "visits_get_ping",
    ("get", "/api/visits/inpatient/board"): "visits_get_bed_board",
    ("post", "/api/visits/inpatient/admissions"): "visits_admit_patient",
    ("get", "/api/visits/inpatient/admissions/{admission_id}"): "visits_get_admission",
    ("post", "/api/visits/inpatient/admissions/{admission_id}/transfer"): "visits_transfer_bed",
    (
        "post",
        "/api/visits/inpatient/admissions/{admission_id}/discharge",
    ): "visits_discharge_patient",
    ("post", "/api/visits/inpatient/beds/{bed_id}/status"): "visits_set_bed_status",
    ("post", "/api/visits/inpatient/charge-due"): "visits_charge_bed_nights",
}


def test_operations_are_pinned() -> None:
    assert module_operations(PREFIX) == OPERATIONS


def test_every_operation_refuses_a_user_without_the_permission(
    make_user: Any, api_client: ApiClient
) -> None:
    make_user("nobody")
    assert api_client.login("nobody").status_code == 200
    assert_role_less_user_is_refused(api_client, OPERATIONS, open_ops={"visits_get_ping"})
