"""In-app notifications of the signed-in user (FEATURES 0.13) and the audit trail viewer
(FEATURES 0.4, ``core.view_audit``)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core import audit
from apps.core import services as core
from apps.core.models import Department, Notification
from conftest import ApiClient
from domain.errors import DomainError

pytestmark = pytest.mark.django_db


# --- notifications --------------------------------------------------------------------------


def test_notifications_are_listed_counted_and_marked_per_user(
    make_user: Any, api_client: ApiClient
) -> None:
    me = make_user("reader", roles=["pharmacist"])
    other = make_user("other", roles=["pharmacist"])
    core.notify_users([me, other], "stock_low", item_id=1, on_hand=3)
    core.notify_users([me], "lab_result_ready", visit_id=9)
    theirs = Notification.objects.get(user=other)
    assert api_client.login("reader").status_code == 200

    assert api_client.get("/api/core/notifications/unread-count").json() == {"count": 2}
    page = api_client.get("/api/core/notifications").json()
    assert [n["kind"] for n in page["items"]] == ["lab_result_ready", "stock_low"]
    assert page["items"][1]["payload"] == {"item_id": 1, "on_hand": 3}

    first = page["items"][0]["id"]
    marked = api_client.post(f"/api/core/notifications/{first}/read")
    assert marked.status_code == 200
    assert marked.json()["read_at"] is not None
    assert api_client.get("/api/core/notifications?unread=true").json()["count"] == 1
    # Another user's notification does not exist for me.
    assert api_client.post(f"/api/core/notifications/{theirs.pk}/read").status_code == 404
    assert api_client.post("/api/core/notifications/read-all").json() == {"updated": 1}
    assert api_client.get("/api/core/notifications/unread-count").json() == {"count": 0}
    theirs.refresh_from_db()
    assert theirs.read_at is None


def test_notifications_need_a_session(api_client: ApiClient) -> None:
    assert api_client.get("/api/core/notifications/unread-count").status_code == 401


def test_a_dedupe_key_notifies_each_user_once(make_user: Any) -> None:
    a = make_user("a1", roles=["manager"])
    b = make_user("b1", roles=["manager"])
    assert core.notify_users([a], "shift_review_pending", dedupe_key="k:1", count=1) == 1
    assert core.notify_users([a, b], "shift_review_pending", dedupe_key="k:1", count=2) == 1
    assert core.notify_users([a, b], "shift_review_pending", dedupe_key="k:1") == 0
    assert Notification.objects.filter(key="k:1").count() == 2
    with pytest.raises(IntegrityError), transaction.atomic():
        Notification.objects.create(user=a, kind="x", key="k:1")
    # Event notifications have no key and may repeat.
    core.notify_users([a], "stock_low")
    core.notify_users([a], "stock_low")
    assert Notification.objects.filter(user=a, kind="stock_low").count() == 2


# --- audit ----------------------------------------------------------------------------------


@pytest.fixture
def auditor(make_user: Any) -> Any:
    return make_user("auditor", roles=["manager"])


def _department_change(actor: Any) -> Department:
    dept = core.create_department(actor, code="AUD", name_ar="قسم", name_en="Audit dept")
    core.update_department(actor, dept.pk, name_en="Audited dept")
    return dept


def test_audit_events_show_who_changed_what(make_user: Any, auditor: Any) -> None:
    admin = make_user("auditadmin", roles=["admin"])
    dept = _department_change(admin)
    page = audit.audit_events(
        audit.AuditFilters(model="core.Department", object_id=str(dept.pk)), page=1, page_size=10
    )
    assert page["count"] == 2
    update, insert = page["items"]
    assert (update.action, insert.action) == ("update", "insert")
    assert update.user == admin
    assert update.reason
    assert [(c.field, c.before, c.after) for c in update.changes] == [
        ("name_en", "Audit dept", "Audited dept")
    ]
    assert ("code", None, "AUD") in [(c.field, c.before, c.after) for c in insert.changes]
    assert update.model_name == "department"


def test_audit_filters_by_user_day_and_action(make_user: Any) -> None:
    admin = make_user("auditadmin2", roles=["admin"])
    someone = make_user("someone", roles=["admin"])
    _department_change(admin)
    by_user = audit.audit_events(audit.AuditFilters(user_id=admin.pk), page=1, page_size=100)
    assert by_user["count"] >= 2
    assert all(e.user_id == admin.pk for e in by_user["items"])
    assert (
        audit.audit_events(
            audit.AuditFilters(user_id=someone.pk, model="core.Department"), page=1, page_size=10
        )["count"]
        == 0
    )
    today = timezone.localdate()
    assert (
        audit.audit_events(
            audit.AuditFilters(
                model="core.Department", date_from=today, date_to=today, action="update"
            ),
            page=1,
            page_size=10,
        )["count"]
        == 1
    )
    assert (
        audit.audit_events(
            audit.AuditFilters(model="core.Department", date_to=today - timedelta(days=1)),
            page=1,
            page_size=10,
        )["count"]
        == 0
    )


def test_audit_refuses_unknown_filters() -> None:
    for filters, code in (
        (audit.AuditFilters(model="core.Nope"), "AUDIT_MODEL_UNKNOWN"),
        (audit.AuditFilters(action="truncate"), "AUDIT_ACTION_UNKNOWN"),
        (
            audit.AuditFilters(
                date_from=timezone.localdate(), date_to=timezone.localdate() - timedelta(days=1)
            ),
            "INVALID_DATE_RANGE",
        ),
    ):
        with pytest.raises(DomainError) as refused:
            audit.audit_events(filters, page=1, page_size=10)
        assert refused.value.code == code


def test_audit_hides_secret_fields() -> None:
    changes = audit._changes(
        "update",
        {"password": "pbkdf2$new", "username": "x", "pgh_id": 3},
        {"password": "pbkdf2$old", "username": "x"},
    )
    assert [(c.field, c.before, c.after) for c in changes] == [("password", "***", "***")]
    assert {m.label for m in audit.audit_models()} >= {"billing.Invoice", "core.Department"}


def test_audit_api_needs_the_permission(
    make_user: Any, auditor: Any, api_client: ApiClient
) -> None:
    make_user("till", roles=["cashier"])
    assert api_client.login("till").status_code == 200
    assert api_client.get("/api/core/audit/events").status_code == 403
    assert api_client.get("/api/core/audit/models").status_code == 403
    api_client.post("/api/auth/logout")
    _department_change(make_user("auditadmin3", roles=["admin"]))
    assert api_client.login("auditor").status_code == 200
    models = api_client.get("/api/core/audit/models").json()
    assert {"label": "core.Department", "app_label": "core", "verbose_name": "department"} in models
    events = api_client.get("/api/core/audit/events?model=core.Department&page_size=5").json()
    assert events["count"] >= 2
    assert events["items"][0]["changes"][0]["field"] == "name_en"
    assert events["items"][0]["user"]["id"] > 0
    bad = api_client.get("/api/core/audit/events?model=core.Nope")
    assert (bad.status_code, bad.json()["code"]) == (409, "AUDIT_MODEL_UNKNOWN")
