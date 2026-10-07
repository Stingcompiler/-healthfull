"""The project's only authentication backend.

``django.contrib.auth.authenticate()`` (used by the Django admin login and by anything
else that logs users in) goes through :func:`apps.core.services.authenticate_credentials`,
so every login path shares the per-address throttle, the per-account lockout and the
``AuthEvent`` audit trail of the API login.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.backends import ModelBackend
from django.http import HttpRequest

from apps.core.models import User


class LockoutBackend(ModelBackend):
    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> User | None:
        from apps.core import services

        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if not username or password is None:
            return None
        result = services.authenticate_credentials(request or HttpRequest(), username, password)
        if isinstance(result, User) and self.user_can_authenticate(result):
            return result
        return None
