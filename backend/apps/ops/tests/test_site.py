"""``GET /api/ops/site`` (ADR 0027): the marketing page is a deployment switch, off by default."""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client

from config.env import env_bool

pytestmark = pytest.mark.django_db


def test_marketing_is_off_by_default() -> None:
    assert env_bool("MARKETING_SITE", False, {}) is False
    body = Client().get("/api/ops/site").json()
    assert body == {"marketing": False, "contact_email": None, "contact_whatsapp": None}


def test_needs_no_session_or_csrf() -> None:
    client = Client(enforce_csrf_checks=True)
    assert client.get("/api/ops/site").status_code == 200
    assert "sessionid" not in client.cookies


def test_on_returns_the_contact_values(settings: Any) -> None:
    settings.MARKETING_SITE = True
    settings.MARKETING_CONTACT_EMAIL = "sales@example.org"
    settings.MARKETING_CONTACT_WHATSAPP = "+249 91 234 5678"
    assert Client().get("/api/ops/site").json() == {
        "marketing": True,
        "contact_email": "sales@example.org",
        "contact_whatsapp": "249912345678",
    }


def test_on_without_contact_shows_none(settings: Any) -> None:
    settings.MARKETING_SITE = True
    settings.MARKETING_CONTACT_EMAIL = ""
    settings.MARKETING_CONTACT_WHATSAPP = ""
    body = Client().get("/api/ops/site").json()
    assert body == {"marketing": True, "contact_email": None, "contact_whatsapp": None}


@pytest.mark.parametrize(
    "email", ["not an email", "a@b", 'x"@y.com', "<s>@y.com", "javascript:alert(1)"]
)
def test_a_malformed_email_is_dropped(settings: Any, email: str) -> None:
    settings.MARKETING_SITE = True
    settings.MARKETING_CONTACT_EMAIL = email
    assert Client().get("/api/ops/site").json()["contact_email"] is None


@pytest.mark.parametrize("number", ["0912345678", "12345", "abc", "2499123456789012345", "+249-9x"])
def test_a_malformed_whatsapp_number_is_dropped(settings: Any, number: str) -> None:
    settings.MARKETING_SITE = True
    settings.MARKETING_CONTACT_WHATSAPP = number
    assert Client().get("/api/ops/site").json()["contact_whatsapp"] is None


def test_off_hides_the_contact_values(settings: Any) -> None:
    settings.MARKETING_SITE = False
    settings.MARKETING_CONTACT_EMAIL = "sales@example.org"
    settings.MARKETING_CONTACT_WHATSAPP = "249912345678"
    assert Client().get("/api/ops/site").json() == {
        "marketing": False,
        "contact_email": None,
        "contact_whatsapp": None,
    }
