"""``/api/auth`` contract: every branch, including CSRF enforcement and lockout."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.core.models import AuthEvent, AuthEventKind, Policy, User
from conftest import TEST_PASSWORD, ApiClient

pytestmark = pytest.mark.django_db

ME_KEYS = {
    "id",
    "username",
    "full_name_ar",
    "full_name_en",
    "roles",
    "permissions",
    "language",
    "theme",
    "must_change_password",
}


def _kinds(user: User | None = None) -> list[str]:
    qs = AuthEvent.objects.order_by("id")
    if user is not None:
        qs = qs.filter(user=user)
    return list(qs.values_list("kind", flat=True))


def _assert_error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.content
    body = response.json()
    assert set(body) == {"code", "message", "details"}
    assert body["code"] == code
    assert isinstance(body["message"], str)
    assert isinstance(body["details"], dict)
    return body


# --- CSRF cookie -------------------------------------------------------------------------


def test_csrf_endpoint_sets_readable_cookie(api_client: ApiClient) -> None:
    response = api_client.django.get("/api/auth/csrf")
    assert response.status_code == 204
    assert response.content == b""
    cookie = response.cookies["csrftoken"]
    assert cookie.value
    assert not cookie["httponly"]
    assert cookie["samesite"] == "Lax"


# --- Login ------------------------------------------------------------------------------


def test_login_success_returns_me_and_starts_session(api_client: ApiClient, make_user: Any) -> None:
    user = make_user(
        "sara",
        roles=["admin"],
        full_name_ar="سارة",
        full_name_en="Sara",
        language="en",
        theme="dark",
    )
    token_before = api_client.fetch_csrf()

    response = api_client.login("sara")

    assert response.status_code == 200, response.content
    body = response.json()
    assert set(body) == ME_KEYS
    assert body == {
        "id": user.pk,
        "username": "sara",
        "full_name_ar": "سارة",
        "full_name_en": "Sara",
        "roles": ["admin"],
        "permissions": sorted(
            [
                "core.manage_roles",
                "core.manage_settings",
                "core.manage_users",
                "core.view_audit",
                "ops.view_status",
            ]
        ),
        "language": "en",
        "theme": "dark",
        "must_change_password": False,
    }
    assert "sessionid" in response.cookies
    assert response.cookies["sessionid"]["httponly"]
    # Login rotates the CSRF token.
    assert api_client.csrftoken
    assert api_client.csrftoken != token_before
    user.refresh_from_db()
    assert user.last_login is not None
    assert _kinds(user) == [AuthEventKind.LOGIN_SUCCESS]
    assert api_client.get("/api/auth/me").status_code == 200


def test_login_session_expiry_follows_policy(api_client: ApiClient, make_user: Any) -> None:
    make_user("idle")
    policy = Policy.load()
    policy.session_idle_minutes = 30
    policy.save()
    assert api_client.login("idle").status_code == 200
    assert api_client.django.session.get_expiry_age() == 30 * 60


def test_login_records_ip_user_agent_and_request_id(api_client: ApiClient, make_user: Any) -> None:
    user = make_user("ua")
    response = api_client.post(
        "/api/auth/login",
        {"username": "ua", "password": TEST_PASSWORD},
        headers={"User-Agent": "pytest-agent", "X-Request-ID": "req-12345678"},
    )
    assert response.status_code == 200
    event = AuthEvent.objects.get(user=user)
    assert event.ip_address == "127.0.0.1"
    assert event.user_agent == "pytest-agent"
    # The audited id is the server's, never the client-supplied one.
    assert event.request_id == response["X-Request-ID"]
    assert event.request_id != "req-12345678"
    assert event.username == "ua"


def test_login_requires_csrf_token(api_client: ApiClient, make_user: Any) -> None:
    make_user("nocsrf")
    response = api_client.post(
        "/api/auth/login", {"username": "nocsrf", "password": TEST_PASSWORD}, csrf=False
    )
    _assert_error(response, 403, "CSRF_FAILED")
    assert "sessionid" not in response.cookies
    assert AuthEvent.objects.count() == 0


def test_login_rejects_wrong_csrf_token(api_client: ApiClient, make_user: Any) -> None:
    make_user("badcsrf")
    api_client.fetch_csrf()
    response = api_client.post(
        "/api/auth/login",
        {"username": "badcsrf", "password": TEST_PASSWORD},
        headers={"X-CSRFToken": "x" * 32},
    )
    _assert_error(response, 403, "CSRF_FAILED")


def test_login_wrong_password(api_client: ApiClient, make_user: Any) -> None:
    user = make_user("wrong")
    body = _assert_error(api_client.login("wrong", "nope-nope"), 401, "INVALID_CREDENTIALS")
    assert body["details"] == {}
    user.refresh_from_db()
    assert user.failed_login_count == 1
    assert user.locked_until is None
    assert _kinds(user) == [AuthEventKind.LOGIN_FAILED]
    assert AuthEvent.objects.get(user=user).details["reason"] == "bad_password"


def test_login_unknown_user_looks_like_wrong_password(api_client: ApiClient) -> None:
    body = _assert_error(api_client.login("ghost", "whatever"), 401, "INVALID_CREDENTIALS")
    assert body["details"] == {}
    event = AuthEvent.objects.get()
    assert event.kind == AuthEventKind.LOGIN_FAILED
    assert event.user is None
    assert event.username == "ghost"
    assert event.details == {"reason": "unknown_user"}


def test_login_inactive_user_is_refused_without_counting(
    api_client: ApiClient, make_user: Any
) -> None:
    user = make_user("gone", is_active=False)
    _assert_error(api_client.login("gone"), 401, "INVALID_CREDENTIALS")
    user.refresh_from_db()
    assert user.failed_login_count == 0
    assert AuthEvent.objects.get(user=user).details == {"reason": "inactive"}


@pytest.mark.parametrize(
    "payload",
    [{}, {"username": "x"}, {"password": "x"}, {"username": "", "password": "x"}, []],
)
def test_login_validation_errors(api_client: ApiClient, payload: Any) -> None:
    body = _assert_error(api_client.post("/api/auth/login", payload), 422, "VALIDATION_ERROR")
    errors = body["details"]["errors"]
    assert errors
    assert all({"loc", "msg", "type"} == set(e) for e in errors)


def test_login_rejects_malformed_json(api_client: ApiClient) -> None:
    response = api_client.django.post(
        "/api/auth/login",
        data="{not json",
        content_type="application/json",
        headers={"X-CSRFToken": api_client.fetch_csrf()},
    )
    assert response.status_code in (400, 422)
    assert response.json()["code"] in ("BAD_REQUEST", "VALIDATION_ERROR")


def test_successful_login_resets_failure_counter(api_client: ApiClient, make_user: Any) -> None:
    user = make_user("retry")
    for _ in range(3):
        assert api_client.login("retry", "bad-password").status_code == 401
    user.refresh_from_db()
    assert user.failed_login_count == 3
    assert api_client.login("retry").status_code == 200
    user.refresh_from_db()
    assert user.failed_login_count == 0
    assert user.locked_until is None


def test_lockout_after_five_failures(api_client: ApiClient, make_user: Any) -> None:
    user = make_user("locky")
    for attempt in range(1, 6):
        _assert_error(api_client.login("locky", "bad-password"), 401, "INVALID_CREDENTIALS")
        user.refresh_from_db()
        assert user.failed_login_count == attempt
    assert user.locked_until is not None
    lock_end = user.locked_until
    assert timedelta(minutes=14) < lock_end - timezone.now() <= timedelta(minutes=15)

    # Even the correct password is refused while locked, and the lock is not extended.
    body = _assert_error(api_client.login("locky"), 423, "ACCOUNT_LOCKED")
    assert body["details"]["locked_until"] == lock_end.isoformat()
    assert 0 < body["details"]["retry_after_seconds"] <= 15 * 60
    _assert_error(api_client.login("locky", "bad-password"), 423, "ACCOUNT_LOCKED")
    user.refresh_from_db()
    assert user.locked_until == lock_end
    assert user.failed_login_count == 5
    assert (
        "sessionid" not in api_client.django.cookies
        or not api_client.django.cookies["sessionid"].value
    )

    kinds = _kinds(user)
    assert kinds.count(AuthEventKind.LOGIN_FAILED) == 5
    assert kinds.count(AuthEventKind.ACCOUNT_LOCKED) == 1
    assert kinds.count(AuthEventKind.LOGIN_LOCKED) == 2
    assert api_client.get("/api/auth/me").status_code == 401


def test_lock_expires_after_fifteen_minutes(api_client: ApiClient, make_user: Any) -> None:
    user = make_user("expired")
    User.objects.filter(pk=user.pk).update(
        failed_login_count=5, locked_until=timezone.now() - timedelta(seconds=1)
    )
    assert api_client.login("expired").status_code == 200
    user.refresh_from_db()
    assert user.failed_login_count == 0
    assert user.locked_until is None


def test_expired_lock_restarts_the_counter(api_client: ApiClient, make_user: Any) -> None:
    user = make_user("again")
    User.objects.filter(pk=user.pk).update(
        failed_login_count=5, locked_until=timezone.now() - timedelta(seconds=1)
    )
    _assert_error(api_client.login("again", "bad-password"), 401, "INVALID_CREDENTIALS")
    user.refresh_from_db()
    assert user.failed_login_count == 1
    assert user.locked_until is None


def test_login_as_another_user_replaces_session(api_client: ApiClient, make_user: Any) -> None:
    make_user("first")
    make_user("second")
    assert api_client.login("first").status_code == 200
    assert api_client.login("second").status_code == 200
    assert api_client.get("/api/auth/me").json()["username"] == "second"


# --- Me ---------------------------------------------------------------------------------


def test_me_requires_authentication(api_client: ApiClient) -> None:
    _assert_error(api_client.get("/api/auth/me"), 401, "NOT_AUTHENTICATED")


def test_me_for_doctor_has_no_admin_permissions(api_client: ApiClient, make_user: Any) -> None:
    make_user("doc", roles=["doctor"])
    api_client.login("doc")
    body = api_client.get("/api/auth/me").json()
    assert body["roles"] == ["doctor"]
    assert body["permissions"] == []


def test_me_for_superuser_lists_every_permission(api_client: ApiClient, make_user: Any) -> None:
    from apps.core.permissions import PERMISSIONS

    make_user("root", is_superuser=True, is_staff=True)
    api_client.login("root")
    body = api_client.get("/api/auth/me").json()
    assert body["permissions"] == sorted(PERMISSIONS)
    assert body["roles"] == []


def test_me_reports_pending_password_change(api_client: ApiClient, make_user: Any) -> None:
    make_user("newbie", must_change_password=True)
    assert api_client.login("newbie").json()["must_change_password"] is True
    me = api_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["must_change_password"] is True


def test_session_of_deactivated_user_is_rejected(api_client: ApiClient, make_user: Any) -> None:
    user = make_user("fired")
    api_client.login("fired")
    User.objects.filter(pk=user.pk).update(is_active=False)
    _assert_error(api_client.get("/api/auth/me"), 401, "NOT_AUTHENTICATED")


# --- Logout -----------------------------------------------------------------------------


def test_logout_ends_session(api_client: ApiClient, make_user: Any) -> None:
    user = make_user("bye")
    api_client.login("bye")
    response = api_client.post("/api/auth/logout")
    assert response.status_code == 204
    assert response.content == b""
    assert api_client.get("/api/auth/me").status_code == 401
    assert _kinds(user) == [AuthEventKind.LOGIN_SUCCESS, AuthEventKind.LOGOUT]


def test_logout_without_session_is_a_no_op(api_client: ApiClient) -> None:
    assert api_client.post("/api/auth/logout").status_code == 204
    assert AuthEvent.objects.count() == 0


def test_logout_requires_csrf(api_client: ApiClient, make_user: Any) -> None:
    make_user("stay")
    api_client.login("stay")
    _assert_error(api_client.post("/api/auth/logout", csrf=False), 403, "CSRF_FAILED")
    assert api_client.get("/api/auth/me").status_code == 200


# --- Preferences ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "language", "theme"),
    [
        ({"language": "en"}, "en", None),
        ({"theme": "warm"}, None, "warm"),
        ({"language": "en", "theme": "dark"}, "en", "dark"),
        ({}, None, None),
        ({"language": None, "theme": None}, None, None),
    ],
)
def test_preferences_are_persisted(
    api_client: ApiClient,
    make_user: Any,
    payload: dict[str, Any],
    language: str | None,
    theme: str | None,
) -> None:
    user = make_user("prefs")
    api_client.login("prefs")
    response = api_client.patch("/api/auth/me/preferences", payload)
    assert response.status_code == 200, response.content
    body = response.json()
    assert (body["language"], body["theme"]) == (language, theme)
    user.refresh_from_db()
    assert (user.language or None, user.theme or None) == (language, theme)


@pytest.mark.parametrize("payload", [{"language": "fr"}, {"theme": "blue"}, {"theme": 3}])
def test_preferences_reject_unknown_values(
    api_client: ApiClient, make_user: Any, payload: dict[str, Any]
) -> None:
    make_user("picky")
    api_client.login("picky")
    _assert_error(api_client.patch("/api/auth/me/preferences", payload), 422, "VALIDATION_ERROR")


def test_preferences_require_auth_and_csrf(api_client: ApiClient, make_user: Any) -> None:
    _assert_error(
        api_client.patch("/api/auth/me/preferences", {"theme": "dark"}), 401, "NOT_AUTHENTICATED"
    )
    make_user("csrfpref")
    api_client.login("csrfpref")
    _assert_error(
        api_client.patch("/api/auth/me/preferences", {"theme": "dark"}, csrf=False),
        403,
        "CSRF_FAILED",
    )


def test_preferences_allowed_while_password_change_pending(
    api_client: ApiClient, make_user: Any
) -> None:
    make_user("pending", must_change_password=True)
    api_client.login("pending")
    response = api_client.patch("/api/auth/me/preferences", {"language": "en"})
    assert response.status_code == 200


# --- Change password --------------------------------------------------------------------


def test_change_password_success_keeps_session(api_client: ApiClient, make_user: Any) -> None:
    user = make_user("changer", must_change_password=True)
    api_client.login("changer")
    response = api_client.post(
        "/api/auth/change-password",
        {"old_password": TEST_PASSWORD, "new_password": "Brand-New-Pass-77"},
    )
    assert response.status_code == 204, response.content
    user.refresh_from_db()
    assert user.check_password("Brand-New-Pass-77")
    assert user.must_change_password is False
    assert user.password_changed_at is not None
    me = api_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["must_change_password"] is False
    assert AuthEventKind.PASSWORD_CHANGED in _kinds(user)
    # The old password no longer works.
    fresh = ApiClient()
    assert fresh.login("changer").status_code == 401
    assert fresh.login("changer", "Brand-New-Pass-77").status_code == 200


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        ("not-my-password", "Brand-New-Pass-77", "old_password_incorrect"),
        (TEST_PASSWORD, TEST_PASSWORD, "password_unchanged"),
        (TEST_PASSWORD, "12345678", "password_rejected"),
        (TEST_PASSWORD, "short", "password_rejected"),
        (TEST_PASSWORD, "password", "password_rejected"),
    ],
)
def test_change_password_rejections(
    api_client: ApiClient, make_user: Any, old: str, new: str, reason: str
) -> None:
    user = make_user("strict")
    api_client.login("strict")
    body = _assert_error(
        api_client.post("/api/auth/change-password", {"old_password": old, "new_password": new}),
        409,
        "PASSWORD_INVALID",
    )
    assert body["details"]["reason"] == reason
    if reason == "password_rejected":
        assert body["details"]["messages"]
        assert all(isinstance(m, str) for m in body["details"]["messages"])
    user.refresh_from_db()
    assert user.check_password(TEST_PASSWORD)
    failed = AuthEvent.objects.filter(user=user, kind=AuthEventKind.PASSWORD_CHANGE_FAILED).get()
    expected: dict[str, Any] = {"reason": reason}
    if reason == "old_password_incorrect":
        expected["failed_count"] = 1  # counts toward the login lockout
    assert failed.details == expected


def test_change_password_messages_follow_user_language(
    api_client: ApiClient, make_user: Any
) -> None:
    make_user("english", language="en")
    api_client.login("english")
    body = api_client.post(
        "/api/auth/change-password", {"old_password": TEST_PASSWORD, "new_password": "short"}
    ).json()
    assert any("too short" in m for m in body["details"]["messages"])


def test_change_password_requires_auth(api_client: ApiClient) -> None:
    _assert_error(
        api_client.post("/api/auth/change-password", {"old_password": "a", "new_password": "b"}),
        401,
        "NOT_AUTHENTICATED",
    )


def test_change_password_validation(api_client: ApiClient, make_user: Any) -> None:
    make_user("val")
    api_client.login("val")
    _assert_error(
        api_client.post("/api/auth/change-password", {"old_password": TEST_PASSWORD}),
        422,
        "VALIDATION_ERROR",
    )


# --- Correlation and audit context ------------------------------------------------------


def test_responses_carry_a_server_generated_request_id(api_client: ApiClient) -> None:
    generated = api_client.get("/api/ops/health")["X-Request-ID"]
    assert len(generated) == 32
    # A client cannot pick (or replay) the id that goes into the audit trail.
    supplied = api_client.get("/api/ops/health", headers={"X-Request-ID": "abc-123-XYZ"})
    assert supplied["X-Request-ID"] != "abc-123-XYZ"
    assert len(supplied["X-Request-ID"]) == 32
    assert supplied["X-Request-ID"] != generated
    rejected = api_client.get("/api/ops/health", headers={"X-Request-ID": "bad id!"})
    assert rejected["X-Request-ID"] != "bad id!"


def test_writes_are_audited_with_user_and_request_id(api_client: ApiClient, make_user: Any) -> None:
    from apps.core.models import UserEvent  # type: ignore[attr-defined]

    user = make_user("audited")
    api_client.login("audited")
    response = api_client.patch(
        "/api/auth/me/preferences", {"theme": "dark"}, headers={"X-Request-ID": "audit-req-0001"}
    )
    assert response.status_code == 200
    event = UserEvent.objects.filter(pgh_obj_id=user.pk, pgh_label="update").latest("pgh_id")
    assert event.theme == "dark"
    assert event.pgh_context is not None
    metadata = event.pgh_context.metadata
    assert metadata["user"] == user.pk
    assert metadata["request_id"] == response["X-Request-ID"]
    assert metadata["client_request_id"] == "audit-req-0001"
    assert metadata["url"] == "/api/auth/me/preferences"
    assert metadata["method"] == "PATCH"


def test_client_ip_honours_forwarded_for_only_when_trusted(settings: Any) -> None:
    from django.test import RequestFactory

    from apps.core.services import client_ip

    request = RequestFactory().get(
        "/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.1"
    )
    settings.TRUST_X_FORWARDED_FOR = False
    assert client_ip(request) == "10.0.0.1"
    settings.TRUST_X_FORWARDED_FOR = True
    assert client_ip(request) == "203.0.113.9"
    assert client_ip(RequestFactory().get("/", REMOTE_ADDR="10.0.0.2")) == "10.0.0.2"
    assert client_ip(RequestFactory().get("/", REMOTE_ADDR="")) is None


def test_client_ip_ignores_forwarded_values_that_are_not_addresses(settings: Any) -> None:
    from django.test import RequestFactory

    from apps.core.services import client_ip

    settings.TRUST_X_FORWARDED_FOR = True
    forged = RequestFactory().get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="not-an-ip")
    assert client_ip(forged) == "10.0.0.1"
    v6 = RequestFactory().get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="2001:DB8::1")
    assert client_ip(v6) == "2001:db8::1"
    assert client_ip(RequestFactory().get("/", REMOTE_ADDR="garbage")) is None


def test_forged_forwarded_for_cannot_break_failure_bookkeeping(
    api_client: ApiClient, make_user: Any, settings: Any
) -> None:
    settings.TRUST_X_FORWARDED_FOR = True
    user = make_user("xff")
    response = api_client.post(
        "/api/auth/login",
        {"username": "xff", "password": "wrong-wrong"},
        headers={"X-Forwarded-For": "not-an-ip"},
    )
    _assert_error(response, 401, "INVALID_CREDENTIALS")
    user.refresh_from_db()
    assert user.failed_login_count == 1
    assert AuthEvent.objects.get(user=user).ip_address == "127.0.0.1"


def test_audit_write_failure_keeps_the_failure_count(
    api_client: ApiClient, make_user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from django.db import DatabaseError

    user = make_user("auditfail")

    def broken_create(*args: Any, **kwargs: Any) -> Any:
        raise DatabaseError("audit table unavailable")

    monkeypatch.setattr(AuthEvent.objects, "create", broken_create)
    _assert_error(api_client.login("auditfail", "wrong-wrong"), 401, "INVALID_CREDENTIALS")
    user.refresh_from_db()
    assert user.failed_login_count == 1


# --- Unknown usernames and per-address throttling ----------------------------------------


def test_unknown_username_locks_exactly_like_an_existing_one(
    api_client: ApiClient, make_user: Any
) -> None:
    """No 401/423 oracle: both kinds of username answer the same sequence."""
    make_user("realname")
    answers: dict[str, list[tuple[int, str]]] = {}
    for name in ("realname", "nobody-here"):
        seq = []
        for i in range(7):
            body = api_client.login(name, f"wrong-{i}")
            seq.append((body.status_code, body.json()["code"]))
        answers[name] = seq
    expected = [(401, "INVALID_CREDENTIALS")] * 5 + [(423, "ACCOUNT_LOCKED")] * 2
    assert answers["realname"] == expected
    assert answers["nobody-here"] == expected
    locked = AuthEvent.objects.filter(username="nobody-here", kind=AuthEventKind.ACCOUNT_LOCKED)
    assert locked.count() == 1
    assert locked.get().user is None


def test_unknown_username_lock_expires(api_client: ApiClient) -> None:
    from apps.core.models import LoginThrottle, ThrottleScope

    LoginThrottle.objects.create(
        scope=ThrottleScope.USERNAME,
        key="phantom",
        count=5,
        locked_until=timezone.now() - timedelta(seconds=1),
    )
    _assert_error(api_client.login("phantom", "x"), 401, "INVALID_CREDENTIALS")
    row = LoginThrottle.objects.get(scope=ThrottleScope.USERNAME, key="phantom")
    assert (row.count, row.locked_until) == (1, None)


def test_too_many_failures_from_one_address_are_rate_limited(
    api_client: ApiClient, make_user: Any, settings: Any
) -> None:
    settings.LOGIN_IP_MAX_FAILURES = 4
    make_user("sprayed1")
    make_user("sprayed2")
    # Password spraying: a few tries per account never locks any one account...
    for name in ("sprayed1", "sprayed2", "sprayed1", "ghost-user"):
        _assert_error(api_client.login(name, "Summer-2026"), 401, "INVALID_CREDENTIALS")
    # ...but the address runs out of budget, and is refused before any password check.
    body = _assert_error(api_client.login("sprayed2"), 429, "RATE_LIMITED")
    assert 0 < body["details"]["retry_after_seconds"] <= settings.LOGIN_IP_WINDOW_SECONDS
    assert User.objects.get(username="sprayed2").failed_login_count == 1
    assert AuthEvent.objects.filter(kind=AuthEventKind.LOGIN_THROTTLED).count() == 1


def test_successful_logins_do_not_use_the_address_budget(
    api_client: ApiClient, make_user: Any, settings: Any
) -> None:
    settings.LOGIN_IP_MAX_FAILURES = 2
    make_user("often")
    for _ in range(5):
        assert api_client.login("often").status_code == 200


def test_address_budget_recovers_after_the_window(
    api_client: ApiClient, make_user: Any, settings: Any
) -> None:
    from apps.core.models import LoginThrottle, ThrottleScope

    settings.LOGIN_IP_MAX_FAILURES = 1
    make_user("patient")
    LoginThrottle.objects.create(
        scope=ThrottleScope.IP,
        key="127.0.0.1",
        count=1,
        window_started_at=timezone.now() - timedelta(seconds=settings.LOGIN_IP_WINDOW_SECONDS),
    )
    assert api_client.login("patient").status_code == 200


# --- Change password: lockout and policy -------------------------------------------------


def test_wrong_current_passwords_lock_the_account_and_end_the_session(
    api_client: ApiClient, make_user: Any
) -> None:
    user = make_user("brute")
    api_client.login("brute")
    for attempt in range(1, 5):
        response = api_client.post(
            "/api/auth/change-password",
            {"old_password": f"guess-{attempt}", "new_password": "Brand-New-Pass-77"},
        )
        _assert_error(response, 409, "PASSWORD_INVALID")
        user.refresh_from_db()
        assert user.failed_login_count == attempt
    response = api_client.post(
        "/api/auth/change-password",
        {"old_password": "guess-5", "new_password": "Brand-New-Pass-77"},
    )
    body = _assert_error(response, 423, "ACCOUNT_LOCKED")
    assert body["details"]["retry_after_seconds"] > 0
    user.refresh_from_db()
    assert user.locked_until is not None
    assert user.check_password(TEST_PASSWORD)
    # The session is gone and the account cannot log in again until the lock ends.
    assert api_client.get("/api/auth/me").status_code == 401
    _assert_error(api_client.login("brute"), 423, "ACCOUNT_LOCKED")
    kinds = _kinds(user)
    assert kinds.count(AuthEventKind.PASSWORD_CHANGE_FAILED) == 5
    assert AuthEventKind.ACCOUNT_LOCKED in kinds


def test_change_password_is_refused_while_locked_without_checking(
    api_client: ApiClient, make_user: Any
) -> None:
    user = make_user("lockedsession")
    api_client.login("lockedsession")
    User.objects.filter(pk=user.pk).update(
        failed_login_count=5, locked_until=timezone.now() + timedelta(minutes=10)
    )
    response = api_client.post(
        "/api/auth/change-password",
        {"old_password": TEST_PASSWORD, "new_password": "Brand-New-Pass-77"},
    )
    _assert_error(response, 423, "ACCOUNT_LOCKED")
    user.refresh_from_db()
    assert user.check_password(TEST_PASSWORD)


def test_correct_current_password_resets_the_counter(api_client: ApiClient, make_user: Any) -> None:
    user = make_user("resetme")
    api_client.login("resetme")
    api_client.post(
        "/api/auth/change-password", {"old_password": "nope-1", "new_password": "Brand-New-77x"}
    )
    user.refresh_from_db()
    assert user.failed_login_count == 1
    response = api_client.post(
        "/api/auth/change-password",
        {"old_password": TEST_PASSWORD, "new_password": "Brand-New-Pass-77"},
    )
    assert response.status_code == 204
    user.refresh_from_db()
    assert user.failed_login_count == 0


@pytest.mark.parametrize(
    "new_password",
    ["Ahmed-Altayeb", "altayeb-ahmed", "Hospital1", "Khartoum-2026", "مستشفى-2026"],
)
def test_change_password_rejects_own_name_and_local_words(
    api_client: ApiClient, make_user: Any, new_password: str
) -> None:
    make_user("ahmed", full_name_en="Ahmed Altayeb", full_name_ar="أحمد الطيب")
    api_client.login("ahmed")
    response = api_client.post(
        "/api/auth/change-password",
        {"old_password": TEST_PASSWORD, "new_password": new_password},
    )
    body = _assert_error(response, 409, "PASSWORD_INVALID")
    assert body["details"]["reason"] == "password_rejected"


def test_change_password_rejects_the_center_name(api_client: ApiClient, make_user: Any) -> None:
    from apps.core.models import CenterProfile

    center = CenterProfile.load()
    center.name_en = "Alamal Specialist Center"
    center.save()
    make_user("centered")
    api_client.login("centered")
    response = api_client.post(
        "/api/auth/change-password",
        {"old_password": TEST_PASSWORD, "new_password": "Alamal#2026x"},
    )
    body = _assert_error(response, 409, "PASSWORD_INVALID")
    assert body["details"]["reason"] == "password_rejected"


def test_preferences_never_chosen_are_null(api_client: ApiClient, make_user: Any) -> None:
    """The client then keeps the device's choice and saves it (ARCHITECTURE 5.1)."""
    make_user("fresh")
    body = api_client.login("fresh").json()
    assert (body["language"], body["theme"]) == (None, None)
    body = api_client.patch("/api/auth/me/preferences", {"theme": "dark"}).json()
    assert (body["language"], body["theme"]) == (None, "dark")
