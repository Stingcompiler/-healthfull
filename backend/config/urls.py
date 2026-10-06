from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.http import HttpRequest, JsonResponse
from django.urls import path, re_path
from django.views.static import serve

from api.errors import error_body
from api.main import api

admin.site.site_header = "Hospital System administration"
admin.site.site_title = "Hospital System admin"


def api_not_found(request: HttpRequest, rest: str = "") -> JsonResponse:
    """JSON 404 for unknown paths under /api/ (instead of Django's HTML page)."""
    return JsonResponse(error_body("NOT_FOUND", "Not found"), status=404)


urlpatterns = [
    # Shadows ninja's HTML 404 "root" view (still reversible, which ninja needs).
    re_path(r"^api/$", api_not_found),
    path("api/", api.urls),
    re_path(r"^api/(?P<rest>.*)$", api_not_found),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:  # pragma: no cover - development convenience only
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    ]
