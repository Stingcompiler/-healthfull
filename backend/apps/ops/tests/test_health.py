from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from django.db import OperationalError
from django.test import Client

from apps.ops import services

pytestmark = pytest.mark.django_db


def test_health_ok(settings: Any) -> None:
    response = Client().get("/api/ops/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "db", "version", "time"}
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["version"] == settings.APP_VERSION
    assert datetime.fromisoformat(body["time"]).tzinfo is not None


def test_health_needs_no_session_or_csrf() -> None:
    client = Client(enforce_csrf_checks=True)
    assert client.get("/api/ops/health").status_code == 200
    assert "sessionid" not in client.cookies


def test_health_reports_version_from_settings(settings: Any) -> None:
    settings.APP_VERSION = "1.2.3"
    assert Client().get("/api/ops/health").json()["version"] == "1.2.3"


def test_health_degraded_when_database_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_cursor() -> None:
        raise OperationalError("connection refused")

    monkeypatch.setattr(services.connection, "cursor", broken_cursor)
    response = Client().get("/api/ops/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "error"
    assert body["version"]


def test_check_database_rejects_unexpected_result(monkeypatch: pytest.MonkeyPatch) -> None:
    class OddCursor:
        def __enter__(self) -> OddCursor:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, sql: str) -> None:
            pass

        def fetchone(self) -> None:
            return None

    monkeypatch.setattr(services.connection, "cursor", lambda: OddCursor())
    assert services.check_database() is False


def test_health_method_not_allowed_is_json() -> None:
    response = Client().post("/api/ops/health")
    assert response.status_code == 405
    assert response.json() == {
        "code": "METHOD_NOT_ALLOWED",
        "message": "Method not allowed",
        "details": {"allowed": ["GET"]},
    }
    assert response["Allow"] == "GET"
