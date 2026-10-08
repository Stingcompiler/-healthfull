"""Reference data that migrations seed, restored for tests after a transactional flush.

Transactional tests (``transaction=True``) end with a TRUNCATE of every table, which also
removes migration-seeded rows (roles, reason codes, chart of accounts, banks, the default cash
price list, ICD-10 codes). The stock/lab/claims/visit test packages call
:func:`ensure_reference_data` before each test and :func:`restore_after_flush` after each
transactional test, so tests that run later (in any app) still find the seeds.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

_MIGRATION_SEEDS = (
    ("apps.payments.migrations.0002_seed_banks", "seed"),
    ("apps.catalog.migrations.0002_seed_cash_price_list", "seed"),
    ("apps.clinical.migrations.0004_seed_icd10", "seed"),
)


def _run_migration_seed(module: str, func: str) -> None:
    from django.apps import apps

    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError:  # pragma: no cover - seed not shipped yet
        return
    getattr(mod, func)(apps, None)


def restore_reference_data() -> None:
    """Re-create every migration seed that is missing (inserts only)."""
    from apps.core.models import ReasonCode
    from apps.core.reason_codes import REASON_CODES, ensure_reason_codes
    from apps.ledger.chart import CHART, ensure_chart_of_accounts
    from apps.ledger.models import Account
    from conftest import ensure_reference_seed

    ensure_reference_seed()
    if ReasonCode.objects.count() < len(REASON_CODES):
        ensure_reason_codes()
    if Account.objects.count() < len(CHART):
        ensure_chart_of_accounts()
    for module, func in _MIGRATION_SEEDS:
        _run_migration_seed(module, func)


def ensure_reference_data() -> None:
    """Cheap check first: restore only when the reason codes or the cash list are gone."""
    from apps.catalog.models import PriceList
    from apps.clinical.models import Icd10Code
    from apps.core.models import ReasonCode
    from apps.ledger.models import Account

    if (
        not ReasonCode.objects.exists()
        or not Account.objects.exists()
        or not PriceList.objects.filter(is_default=True).exists()
        or not Icd10Code.objects.exists()
    ):
        restore_reference_data()


def restore_after_flush(item: pytest.Item, nextitem: pytest.Item | None = None) -> None:
    """Call from ``pytest_runtest_teardown`` after the item's own teardown.

    Nothing to restore after the last test of the session (``nextitem`` is None): by then
    pytest-django has destroyed the test database and pointed the connection back at the
    runtime database, which must never receive test seeds. The connection must name the
    test database (``test_...``) for the same reason.
    """
    from django.db import connection
    from pytest_django.plugin import blocking_manager_key

    marker = item.get_closest_marker("django_db")
    if marker is None or not marker.kwargs.get("transaction") or nextitem is None:
        return
    if not str(connection.settings_dict.get("NAME", "")).startswith("test_"):
        return
    blocker: Any = item.config.stash[blocking_manager_key]
    with blocker.unblock():
        restore_reference_data()
