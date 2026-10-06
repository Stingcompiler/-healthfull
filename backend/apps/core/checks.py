"""System checks (run by ``manage.py check``, ``migrate``, ``runserver`` and the test suite)."""

from __future__ import annotations

from typing import Any

from django.core.checks import CheckMessage, Error, register


@register()
def check_required_permissions_registered(
    app_configs: Any = None, **kwargs: Any
) -> list[CheckMessage]:
    """``core.E001``: every ``@require_perm`` code must be in the permission registry."""
    import api.main  # noqa: F401  (imports every router so their decorators have run)
    from api.permissions import REQUIRED_CODES
    from apps.core.permissions import is_registered

    return [
        Error(
            f"Permission code {code!r} is used by @require_perm but never registered.",
            hint="Call apps.core.permissions.register_permission() in the app's permissions.py.",
            id="core.E001",
        )
        for code in sorted(REQUIRED_CODES)
        if not is_registered(code)
    ]
