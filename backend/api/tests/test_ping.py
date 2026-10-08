"""``GET /api/<module>/ping``: every module router is mounted, authenticated and documented."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from api.tests.test_main import PING_MODULES
from apps.core.management.commands.export_openapi import render_schema
from conftest import ApiClient


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return dict(json.loads(render_schema()))


@pytest.mark.django_db
@pytest.mark.parametrize("module", PING_MODULES)
def test_ping_answers_a_logged_in_user(
    api_client: ApiClient, make_user: Callable[..., Any], module: str
) -> None:
    make_user("pinger")
    assert api_client.login("pinger").status_code == 200
    response = api_client.get(f"/api/{module}/ping")
    assert response.status_code == 200, response.content
    assert response.json() == {"module": module}


@pytest.mark.django_db
@pytest.mark.parametrize("module", PING_MODULES)
def test_ping_requires_a_session(api_client: ApiClient, module: str) -> None:
    response = api_client.get(f"/api/{module}/ping")
    assert response.status_code == 401
    assert response.json() == {
        "code": "NOT_AUTHENTICATED",
        "message": "Authentication required",
        "details": {},
    }


@pytest.mark.django_db
@pytest.mark.parametrize("module", PING_MODULES)
def test_ping_refuses_a_pending_password_change(
    api_client: ApiClient, make_user: Callable[..., Any], module: str
) -> None:
    make_user("newbie", must_change_password=True)
    assert api_client.login("newbie").status_code == 200
    response = api_client.get(f"/api/{module}/ping")
    assert response.status_code == 403
    assert response.json()["code"] == "PASSWORD_CHANGE_REQUIRED"


@pytest.mark.parametrize("module", PING_MODULES)
def test_ping_is_documented(schema: dict[str, Any], module: str) -> None:
    op = schema["paths"][f"/api/{module}/ping"]["get"]
    assert op["operationId"] == f"{module}_get_ping"
    assert op["tags"] == [module]
    assert op["security"], "ping must require a session"
    responses = op["responses"]
    assert set(responses) == {"200", "401", "403"}
    ok = responses["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ok.endswith("/PingOut")
    for status in ("401", "403"):
        ref = responses[status]["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/ErrorOut")
    ping_out = schema["components"]["schemas"]["PingOut"]
    assert ping_out["required"] == ["module"]
