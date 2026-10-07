"""Plain Django views used by settings (outside ninja's handler chain)."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.views.csrf import csrf_failure as django_csrf_failure

from api.errors import error_response


def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    """``CSRF_FAILURE_VIEW``: the JSON error shape under /api/, Django's page elsewhere."""
    if request.path.startswith("/api/"):
        return error_response(403, "CSRF_FAILED", "CSRF verification failed")
    return django_csrf_failure(request, reason=reason)
