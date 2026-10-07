"""Refuse to run e2e data commands against a database that is not a throwaway one.

``seed_e2e`` resets accounts to a known test password and ``e2e_fixture`` writes patients,
invoices and money rows. Both run only when DEBUG is on AND the database is a test one (name
``e2e_*`` or ``test_*``), or when ``ALLOW_SEED_E2E=1`` says so explicitly (``make seed`` on
the development database).
"""

from __future__ import annotations

import os
import re

from django.conf import settings
from django.core.management.base import CommandError
from django.db import connection

#: Databases the e2e commands may write without ALLOW_SEED_E2E=1.
TEST_DB_NAME = re.compile(r"^(e2e|test)_[A-Za-z0-9_]+$")


def require_test_database(command: str) -> None:
    """Raise ``CommandError`` unless the current database may receive e2e data."""
    if os.environ.get("ALLOW_SEED_E2E") == "1":
        return
    db_name = str(connection.settings_dict.get("NAME") or "")
    if not settings.DEBUG:
        raise CommandError(
            f"Refusing to run {command} with DEBUG off. Set ALLOW_SEED_E2E=1 if this really "
            "is a test database."
        )
    if not TEST_DB_NAME.match(db_name):
        raise CommandError(
            f"Refusing to run {command} on {db_name!r}: it writes test accounts and data. Only "
            "e2e_* / test_* databases are used unless ALLOW_SEED_E2E=1 is set."
        )
