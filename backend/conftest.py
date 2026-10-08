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


def ensure_reference_seed() -> None:
    """Re-create what migration 0002 seeds (roles, CenterProfile, Policy) if missing.

    Transactional tests end with a TRUNCATE of every table, which also removes rows that
    migrations inserted. Inserts only: rows that exist are left alone, so this writes no
    history events when nothing is missing.
    """
    from apps.core.models import CenterProfile, Policy, Role
    from apps.core.roles import ROLES

    for role in ROLES:
        Role.objects.get_or_create(
            code=role.code, defaults={"name_ar": role.name_ar, "name_en": role.name_en}
        )
    CenterProfile.load()
    Policy.load()


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup: None, django_db_blocker: Any) -> None:
    """Standard setup, then restore the migration seed (a reused DB may have been flushed)."""
    with django_db_blocker.unblock():
        ensure_reference_seed()


@pytest.fixture(autouse=True)
def _reseed_for_transactional_tests(request: pytest.FixtureRequest) -> None:
    """Each transactional test starts with the migration seed, even after an earlier flush."""
    marker = request.node.get_closest_marker("django_db")
    transactional = marker is not None and bool(
        marker.kwargs.get("transaction", marker.args[0] if marker.args else False)
    )
    if transactional or "transactional_db" in request.fixturenames:
        request.getfixturevalue("transactional_db")
        ensure_reference_seed()


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


def router_operations(prefix: str) -> set[tuple[str, str, str, str | None]]:
    """``(method, path, operation id, required permission)`` of every operation of one module
    router (``"/core"``), so a module test pins its whole API surface exactly."""
    from api.main import api

    return {
        (method, path, str(op.operation_id), getattr(op.view_func, "required_permission", None))
        for router_prefix, router in api._routers
        if router_prefix == prefix
        for path, path_view in router.path_operations.items()
        for op in path_view.operations
        for method in op.methods
    }
