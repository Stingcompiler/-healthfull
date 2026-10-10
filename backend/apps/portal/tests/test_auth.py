"""Portal sign-in, sessions and abuse control (ADR 0016)."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any

import pytest
from django.contrib.auth import hashers
from django.db import connection
from django.utils import timezone

from apps.core.e2e.fixtures import run_fixture
from apps.patients import services as patient_services
from apps.patients.models import Patient
from apps.portal import conf, services
from apps.portal.models import (
    PortalAccessCode,
    PortalEvent,
    PortalEventKind,
    PortalSession,
    PortalThrottle,
)
from apps.portal.tests.conftest import PortalClient
from conftest import ApiClient

pytestmark = pytest.mark.django_db

INVALID = {
    "code": "PORTAL_INVALID_CREDENTIALS",
    "message": "The file number, phone number or code is not right",
    "details": {},
}


# --- sign-in -----------------------------------------------------------------------------


def test_sign_in_sets_only_the_portal_cookie(world: dict[str, Any], portal: PortalClient) -> None:
    a = world["a"]
    response = portal.sign_in(a)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["file_no"] == a["patient"]["file_no"]
    assert body["phone_masked"].endswith(a["patient"]["phone"][-3:])
    assert body["idle_seconds"] == 15 * 60
    cookie = response.cookies[conf.COOKIE_NAME]
    assert cookie["httponly"]
    assert cookie["samesite"] == "Strict"
    assert cookie["path"] == "/api/portal"
    assert "sessionid" not in response.cookies  # never a staff session
    # Only the hash of the token is stored.
    token = cookie.value
    session = PortalSession.objects.get()
    assert session.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in session.token_hash
    assert portal.get("/api/portal/me").status_code == 200


def test_session_probe_answers_without_an_error(
    world: dict[str, Any], portal: PortalClient
) -> None:
    assert portal.get("/api/portal/session").json() == {"signed_in": False, "me": None}
    portal.sign_in(world["a"])
    body = portal.get("/api/portal/session").json()
    assert body["signed_in"] is True
    assert body["me"]["file_no"] == world["a"]["patient"]["file_no"]
    an_hour_ago = timezone.now() - timedelta(hours=1)
    PortalSession.objects.update(created_at=an_hour_ago, last_seen_at=an_hour_ago)
    assert portal.get("/api/portal/session").json() == {"signed_in": False, "me": None}


def test_sign_in_needs_csrf(world: dict[str, Any], portal: PortalClient) -> None:
    a = world["a"]
    response = portal.post(
        "/api/portal/session",
        {"file_no": a["patient"]["file_no"], "phone": a["patient"]["phone"], "code": a["code"]},
        csrf=False,
    )
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"
    assert not PortalSession.objects.exists()


@pytest.mark.parametrize(
    "override",
    [
        {"code": "0000 0000"},
        {"code": "12"},
        {"phone": "0999999999"},
        {"file_no": "PT-2099-999999"},
        {"file_no": "nonsense"},
    ],
    ids=["wrong-code", "malformed-code", "wrong-phone", "unknown-file", "garbage-file"],
)
def test_every_refusal_looks_the_same(
    world: dict[str, Any], portal: PortalClient, override: dict[str, str]
) -> None:
    response = portal.sign_in(world["a"], **override)
    assert response.status_code == 401
    assert response.json() == INVALID
    assert conf.COOKIE_NAME not in response.cookies


@pytest.mark.parametrize(
    "override",
    [{"code": "0000 0000"}, {"phone": "0999999999"}, {"file_no": "PT-2099-999999"}],
    ids=["wrong-code", "wrong-phone", "unknown-file"],
)
def test_every_refusal_costs_one_password_hash(
    world: dict[str, Any],
    portal: PortalClient,
    monkeypatch: pytest.MonkeyPatch,
    override: dict[str, str],
) -> None:
    """Timing: an unknown file, a wrong phone and a wrong code do the same hashing work."""
    calls: list[str] = []
    real_make, real_check = hashers.make_password, hashers.check_password

    def make(*args: Any, **kwargs: Any) -> str:
        calls.append("make")
        return real_make(*args, **kwargs)

    def check(*args: Any, **kwargs: Any) -> bool:
        calls.append("check")
        return real_check(*args, **kwargs)

    monkeypatch.setattr(services, "make_password", make)
    monkeypatch.setattr(services, "check_password", check)
    assert portal.sign_in(world["a"], **override).status_code == 401
    assert len(calls) == 1


def test_loose_file_number_and_arabic_digits_sign_in(world: dict[str, Any]) -> None:
    a = world["a"]
    year, seq = a["patient"]["file_no"].split("-")[1:]
    arabic = a["code"].translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
    response = PortalClient().sign_in(
        a, file_no=f"{year}-{int(seq)}", code=arabic, phone="+249" + a["patient"]["phone"][1:]
    )
    assert response.status_code == 200, response.content


def test_code_is_stored_hashed_and_expires(world: dict[str, Any]) -> None:
    a = world["a"]
    row = PortalAccessCode.objects.get(patient_id=a["patient"]["id"], revoked_at__isnull=True)
    assert a["code"].replace(" ", "") not in row.code_hash
    assert abs(row.expires_at - row.created_at - timedelta(days=30)) < timedelta(minutes=1)
    PortalAccessCode.objects.filter(pk=row.pk).update(
        created_at=timezone.now() - timedelta(days=31), expires_at=timezone.now()
    )
    assert PortalClient().sign_in(a).json() == INVALID


def test_a_new_receipt_code_revokes_the_old_one_and_its_sessions(world: dict[str, Any]) -> None:
    a = world["a"]
    old = PortalClient()
    assert old.sign_in(a).status_code == 200
    fresh = run_fixture("portal_code", {"payment": a["payment"]["id"]})
    assert fresh["code"] != a["code"]
    assert old.get("/api/portal/me").status_code == 401  # the session of the old code ended
    assert PortalClient().sign_in(a).status_code == 401
    assert PortalClient().sign_in(a, code=fresh["code"]).status_code == 200
    ended = PortalSession.objects.exclude(ended_at=None).get()
    assert ended.end_reason == "revoked"


# --- lockout and throttling --------------------------------------------------------------


def _fail(who: dict[str, Any], times: int, **override: str) -> list[int]:
    client = PortalClient()
    return [client.sign_in(who, **override).status_code for _ in range(times)]


@pytest.mark.parametrize("known", [True, False], ids=["known-file", "unknown-file"])
def test_a_file_number_locks_after_five_failures(world: dict[str, Any], known: bool) -> None:
    who = world["a"]
    override = {"code": "1111 1111"} if known else {"file_no": "PT-2098-000001"}
    assert _fail(who, 5, **override) == [401] * 5
    locked = PortalClient().sign_in(who, **override)
    assert locked.status_code == 423
    assert locked.json()["code"] == "PORTAL_LOCKED"
    assert 0 < locked.json()["details"]["retry_after_seconds"] <= 15 * 60
    if known:  # even the right code is refused while the file number is locked
        assert PortalClient().sign_in(who).status_code == 423
    assert PortalEvent.objects.filter(kind=PortalEventKind.LOGIN_LOCKED).count() >= 1


def test_wrong_codes_lock_the_code_for_good(world: dict[str, Any]) -> None:
    a = world["a"]
    assert _fail(a, 5, code="1111 1111") == [401] * 5
    row = PortalAccessCode.objects.get(patient_id=a["patient"]["id"], revoked_at__isnull=True)
    assert row.failed_attempts == 5
    assert row.locked_at is not None
    assert PortalEvent.objects.filter(kind=PortalEventKind.CODE_LOCKED).exists()
    PortalThrottle.objects.all().delete()  # the file lock has passed
    assert PortalClient().sign_in(a).json() == INVALID  # the right code no longer works
    fresh = run_fixture("portal_code", {"payment": a["payment"]["id"]})
    assert PortalClient().sign_in(a, code=fresh["code"]).status_code == 200


def test_wrong_phone_does_not_count_against_the_code(world: dict[str, Any]) -> None:
    a = world["a"]
    _fail(a, 4, phone="0999999999")
    row = PortalAccessCode.objects.get(patient_id=a["patient"]["id"], revoked_at__isnull=True)
    assert row.failed_attempts == 0
    assert PortalClient().sign_in(a).status_code == 200  # 4 failures: not locked yet
    row.refresh_from_db()
    assert row.last_used_at is not None


def test_success_clears_the_file_counter(world: dict[str, Any]) -> None:
    a = world["a"]
    _fail(a, 4, code="1111 1111")
    assert PortalClient().sign_in(a).status_code == 200
    assert _fail(a, 4, code="1111 1111") == [401] * 4  # counting starts again


def test_an_address_is_throttled(world: dict[str, Any], settings: Any) -> None:
    settings.PORTAL_LOGIN_IP_MAX_FAILURES = 3
    for n in range(3):
        assert PortalClient().sign_in(world["a"], file_no=f"PT-2097-00000{n}").status_code == 401
    response = PortalClient().sign_in(world["a"])
    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMITED"
    assert PortalEvent.objects.filter(kind=PortalEventKind.LOGIN_THROTTLED).exists()


# --- sessions ----------------------------------------------------------------------------


def test_session_idles_out(signed_in: dict[str, PortalClient]) -> None:
    session = PortalSession.objects.filter(ended_at=None).first()
    assert session is not None
    PortalSession.objects.update(
        created_at=timezone.now() - timedelta(minutes=20),
        last_seen_at=timezone.now() - timedelta(minutes=16),
    )
    assert signed_in["a"].get("/api/portal/me").status_code == 401
    assert set(PortalSession.objects.values_list("end_reason", flat=True)) <= {"expired", ""}


def test_session_ends_at_the_absolute_limit(signed_in: dict[str, PortalClient]) -> None:
    PortalSession.objects.update(
        created_at=timezone.now() - timedelta(hours=4, minutes=1),
        last_seen_at=timezone.now() - timedelta(minutes=1),
    )
    assert signed_in["a"].get("/api/portal/me").status_code == 401


def test_use_keeps_the_session_alive(signed_in: dict[str, PortalClient]) -> None:
    before = timezone.now() - timedelta(minutes=10)
    PortalSession.objects.update(created_at=before, last_seen_at=before)
    assert signed_in["a"].get("/api/portal/me").status_code == 200
    assert PortalSession.objects.filter(last_seen_at__gt=before).count() == 1


def test_logout_ends_the_session_and_clears_the_cookie(signed_in: dict[str, PortalClient]) -> None:
    client = signed_in["a"]
    token = client.portal_cookie
    response = client.post("/api/portal/session/logout")
    assert response.status_code == 204
    assert response.cookies[conf.COOKIE_NAME].value == ""
    assert (
        PortalSession.objects.get(
            token_hash=hashlib.sha256(str(token).encode()).hexdigest()
        ).end_reason
        == "logout"
    )
    # Replaying the old token does not bring the session back.
    replay = PortalClient()
    replay.django.cookies[conf.COOKIE_NAME] = str(token)
    assert replay.get("/api/portal/me").status_code == 401
    assert client.post("/api/portal/session/logout").status_code == 204  # idempotent
    assert signed_in["b"].get("/api/portal/me").status_code == 200  # others unaffected
    assert PortalEvent.objects.filter(kind=PortalEventKind.LOGOUT).count() == 1


def test_logout_needs_csrf(signed_in: dict[str, PortalClient]) -> None:
    response = signed_in["a"].post("/api/portal/session/logout", csrf=False)
    assert response.status_code == 403
    assert signed_in["a"].get("/api/portal/me").status_code == 200


def test_unsafe_portal_calls_need_csrf(
    signed_in: dict[str, PortalClient], world: dict[str, Any]
) -> None:
    response = signed_in["a"].post(
        f"/api/portal/appointments/{world['a']['appointment']['id']}/cancel", csrf=False
    )
    assert response.status_code == 403


@pytest.mark.parametrize("token", ["", "x", "a" * 500])
def test_forged_tokens_are_refused(world: dict[str, Any], token: str) -> None:
    client = PortalClient()
    client.django.cookies[conf.COOKIE_NAME] = token
    assert client.get("/api/portal/me").status_code == 401


# --- separation from staff sessions -------------------------------------------------------


def test_portal_cookie_opens_no_staff_endpoint(
    signed_in: dict[str, PortalClient], world: dict[str, Any]
) -> None:
    client = signed_in["a"]
    for path in (
        "/api/auth/me",
        f"/api/patients/{world['a']['patient']['id']}",
        f"/api/payments/payments/{world['a']['payment']['id']}/receipt",
        "/api/portal/ping",
    ):
        response = client.get(path)
        assert response.status_code == 401, (path, response.content)


def test_staff_session_opens_no_portal_endpoint(world: dict[str, Any]) -> None:
    from apps.core.models import User

    staff_client = ApiClient()

    root = User.objects.get(username="root")
    staff_client.django.force_login(root)  # a superuser holds every permission
    assert staff_client.get("/api/auth/me").status_code == 200
    for path in ("/api/portal/me", "/api/portal/results", "/api/portal/balance"):
        assert staff_client.get(path).status_code == 401


def test_portal_responses_are_never_cached(signed_in: dict[str, PortalClient]) -> None:
    for path in ("/api/portal/me", "/api/portal/results", "/api/portal/session"):
        assert signed_in["a"].get(path)["Cache-Control"] == "no-store"


def test_a_real_account_with_the_reserved_name_is_never_used(world: dict[str, Any]) -> None:
    from django.core.exceptions import ImproperlyConfigured

    from apps.core.models import User

    User.objects.filter(username=services.PORTAL_ACTOR_USERNAME).delete()
    impostor = User(username=services.PORTAL_ACTOR_USERNAME, must_change_password=False)
    impostor.set_password("Some-Real-Pass-1")
    impostor.save()
    with pytest.raises(ImproperlyConfigured):
        services.portal_actor()


def test_portal_actor_can_never_sign_in(world: dict[str, Any]) -> None:
    actor = services.portal_actor()
    assert not actor.is_active
    assert not actor.has_usable_password()
    assert not actor.roles.exists()
    assert ApiClient().login(services.PORTAL_ACTOR_USERNAME, "anything").status_code == 401


# --- merges and audit --------------------------------------------------------------------


def test_a_merged_file_signs_in_to_the_surviving_person(world: dict[str, Any]) -> None:
    a, b = world["a"], world["b"]
    source = Patient.objects.get(pk=a["patient"]["id"])
    target = Patient.objects.get(pk=b["patient"]["id"])
    from apps.core.models import User

    supervisor = User.objects.get(username="admin")
    patient_services.merge_patients(source, target, actor=supervisor, reason_note="same person")
    client = PortalClient()
    assert client.sign_in(a).status_code == 200
    assert client.get("/api/portal/me").json()["file_no"] == target.file_no
    lines = {r["line_id"] for r in client.get("/api/portal/results").json()}
    assert lines == {a["approved_line"], b["approved_line"]}


def test_portal_events_are_append_only(world: dict[str, Any]) -> None:
    PortalClient().sign_in(world["a"], code="1111 1111")
    event = PortalEvent.objects.filter(kind=PortalEventKind.LOGIN_FAILED).get()
    assert event.file_no == world["a"]["patient"]["file_no"]
    with pytest.raises(Exception, match=r"append_only|protect|Cannot"), connection.cursor() as cur:
        cur.execute("UPDATE portal_portalevent SET file_no = 'x' WHERE id = %s", [event.pk])
