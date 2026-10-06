"""Shared pytest configuration: Hypothesis profiles and API/user fixtures.

Hypothesis profiles: ``dev`` (default) and ``ci`` (derandomized, more examples). Select with
``HYPOTHESIS_PROFILE=ci``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from typing import Any

import pytest
from django.test import Client
from hypothesis import HealthCheck
from hypothesis import settings as hypothesis_settings

hypothesis_settings.register_profile(
    "ci",
    derandomize=True,
    database=None,
    max_examples=300,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
hypothesis_settings.register_profile("dev", max_examples=100, deadline=None)
hypothesis_settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))

TEST_PASSWORD = "Correct-Horse-91"
_SAFE = {"GET", "HEAD", "OPTIONS"}


@pytest.fixture(autouse=True)
def _fast_password_hashing(settings: Any) -> None:
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


class ApiClient:
    """Django test client that enforces CSRF like a browser and speaks JSON."""

    def __init__(self) -> None:
        self.django = Client(enforce_csrf_checks=True)

    @property
    def csrftoken(self) -> str | None:
        cookie = self.django.cookies.get("csrftoken")
        return cookie.value if cookie else None

    def fetch_csrf(self) -> str:
        response = self.django.get("/api/auth/csrf")
        assert response.status_code == 204
        token = self.csrftoken
        assert token
        return token

    def request(
        self,
        method: str,
        path: str,
        data: Any = None,
        *,
        csrf: bool = True,
        headers: dict[str, str] | None = None,
    ) -> Any:
        hdrs = dict(headers or {})
        if csrf and method.upper() not in _SAFE:
            hdrs.setdefault("X-CSRFToken", self.csrftoken or self.fetch_csrf())
        kwargs: dict[str, Any] = {"headers": hdrs}
        if data is not None:
            kwargs["data"] = json.dumps(data)
            kwargs["content_type"] = "application/json"
        return getattr(self.django, method.lower())(path, **kwargs)

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, data: Any = None, **kwargs: Any) -> Any:
        return self.request("POST", path, data, **kwargs)

    def patch(self, path: str, data: Any = None, **kwargs: Any) -> Any:
        return self.request("PATCH", path, data, **kwargs)

    def login(self, username: str, password: str = TEST_PASSWORD) -> Any:
        return self.post("/api/auth/login", {"username": username, "password": password})


@pytest.fixture
def api_client() -> ApiClient:
    return ApiClient()


@pytest.fixture
def make_user(db: None) -> Callable[..., Any]:
    """Create a user with the given role codes. Password defaults to ``TEST_PASSWORD``."""
    from apps.core.models import Role, User, UserRole

    counter = {"n": 0}

    def _make(
        username: str | None = None,
        *,
        roles: Iterable[str] = (),
        password: str = TEST_PASSWORD,
        must_change_password: bool = False,
        **extra: Any,
    ) -> User:
        counter["n"] += 1
        user = User(
            username=username or f"user{counter['n']}",
            must_change_password=must_change_password,
            **extra,
        )
        user.set_password(password)
        user.save()
        for code in roles:
            UserRole.objects.create(user=user, role=Role.objects.get(code=code))
        return user

    return _make
