"""Login and logout signal receivers: one audit and session policy for every login path.

``user_logged_in`` / ``user_logged_out`` fire for the API (``apps.core.services``), the
Django admin and any other ``django.contrib.auth.login()`` call, so the session idle
timeout from ``Policy`` and the ``AuthEvent`` rows cannot be skipped by a second door.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.http import HttpRequest

from apps.core.models import User


@receiver(user_logged_in, dispatch_uid="core.on_user_logged_in")
def _on_user_logged_in(sender: Any, request: HttpRequest | None, user: Any, **kwargs: Any) -> None:
    from apps.core import services

    if request is not None and isinstance(user, User):
        services.on_user_logged_in(request, user)


@receiver(user_logged_out, dispatch_uid="core.on_user_logged_out")
def _on_user_logged_out(sender: Any, request: HttpRequest | None, user: Any, **kwargs: Any) -> None:
    from apps.core import services

    if request is not None and isinstance(user, User):
        services.on_user_logged_out(request, user)
