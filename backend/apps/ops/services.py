"""Operational checks (FEATURES 0.8). Disk, backup and restore status arrive in Phase 6."""

from __future__ import annotations

from typing import Any

import structlog
from django.conf import settings
from django.db import connection
from django.utils import timezone

logger = structlog.get_logger(__name__)


def check_database() -> bool:
    """True if a trivial query succeeds on the default database."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
    except Exception:
        logger.warning("health.db_unavailable", exc_info=True)
        return False
    return row is not None and row[0] == 1


def health() -> dict[str, Any]:
    db_ok = check_database()
    return {
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "error",
        "version": settings.APP_VERSION,
        "time": timezone.now(),
    }
