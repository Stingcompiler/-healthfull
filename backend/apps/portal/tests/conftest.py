"""Portal test data: the e2e seed plus two portal patients built through the services."""

from __future__ import annotations

from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.utils.module_loading import autodiscover_modules

from apps.core.e2e.fixtures import run_fixture
from apps.portal import conf
from conftest import ApiClient

autodiscover_modules("e2e_fixtures")


@pytest.fixture
def seeded(settings: Any, db: None) -> None:
    settings.DEBUG = True
    call_command("seed_e2e", stdout=StringIO())


@pytest.fixture
def world(seeded: None) -> dict[str, dict[str, Any]]:
    """Two patients, each with an approved CBC, an unapproved malaria test, a prescription,
    an approved paid invoice, a receipt with a portal code, and an upcoming appointment."""
    return {
        "a": run_fixture("portal_patient", {"appointment": True}),
        "b": run_fixture("portal_patient", {"appointment": True}),
    }


class PortalClient(ApiClient):
    """A browser on the portal: CSRF like the SPA, its own cookie jar."""

    def sign_in(self, who: dict[str, Any], **override: str) -> Any:
        body = {
            "file_no": who["patient"]["file_no"],
            "phone": who["patient"]["phone"],
            "code": who["code"],
        }
        body.update(override)
        return self.post("/api/portal/session", body)

    @property
    def portal_cookie(self) -> str | None:
        cookie = self.django.cookies.get(conf.COOKIE_NAME)
        return cookie.value if cookie and cookie.value else None


@pytest.fixture
def portal() -> PortalClient:
    return PortalClient()


@pytest.fixture
def signed_in(world: dict[str, dict[str, Any]]) -> dict[str, PortalClient]:
    """Patient A and patient B, each signed in on their own client."""
    clients = {}
    for key in ("a", "b"):
        client = PortalClient()
        assert client.sign_in(world[key]).status_code == 200
        clients[key] = client
    return clients
