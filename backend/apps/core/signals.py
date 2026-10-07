"""Login and logout signal receivers: one audit and session policy for every login path.

``user_logged_in`` / ``user_logged_out`` fire for the API (``apps.core.services``), the
Django admin and any other ``django.contrib.auth.login()`` call, so the session idle
timeout from ``Policy`` and the ``AuthEvent`` rows cannot be skipped by a second door.

After every ``migrate`` the ``pgtrigger`` ignore hook is locked down
(``apps.core.db.lock_trigger_ignore``): trigger installs re-create it, and its stock body
lets any session switch the database guards off with a session setting.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db.models.signals import post_migrate
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


@receiver(post_migrate, dispatch_uid="core.lock_trigger_ignore")
def _lock_trigger_ignore(sender: Any, using: str = "default", **kwargs: Any) -> None:
    from apps.core.db import lock_trigger_ignore

    lock_trigger_ignore(using)
