"""The migration that narrows refunds to cash from a credit note (ADR 0024) checks the data
first and stops with a clear message instead of rewriting anything."""

from __future__ import annotations

import importlib
from decimal import Decimal

import pytest
from django.db import connection

from apps.core.tests import builders as b
from apps.payments.models import Refund

pytestmark = pytest.mark.django_db

migration = importlib.import_module("apps.payments.migrations.0005_refund_cash_from_credit_note")


def _drop_new_constraints() -> None:
    """Let old-shaped rows in, as they could exist before the migration (rolled back after)."""
    with connection.cursor() as cursor:
        for name in ("payments_refund_from_credit_note", "payments_refund_cash_only"):
            cursor.execute(f"ALTER TABLE payments_refund DROP CONSTRAINT {name}")
        cursor.execute("ALTER TABLE payments_refund DROP CONSTRAINT payments_refund_method_valid")


def test_no_violations_on_clean_data() -> None:
    inv = b.approved_invoice()
    Refund.objects.create(
        number=f"RF-{b.n()}",
        patient=inv.patient,
        amount=Decimal("5"),
        credit_note=b.draft_credit_note(inv),
        reason_code=b.reason("refund"),
        requested_by=b.user(),
    )
    with connection.cursor() as cursor:
        assert migration.violations(cursor) == []
        migration.verify_refunds_fit(cursor)  # does not raise


def test_rows_that_do_not_fit_stop_the_migration_and_are_named() -> None:
    inv = b.approved_invoice()
    _drop_new_constraints()
    Refund.objects.create(
        number="RF-OLD-1",
        patient=inv.patient,
        amount=Decimal("5"),
        service_line=inv.lines.get().service_line,
        reason_code=b.reason("refund"),
        requested_by=b.user(),
    )
    Refund.objects.create(
        number="RF-OLD-2",
        patient=inv.patient,
        amount=Decimal("5"),
        method="bank_transfer",
        bank=b.bank("RFX"),
        reference="TRX-9",
        credit_note=b.draft_credit_note(inv),
        reason_code=b.reason("refund"),
        requested_by=b.user(),
    )
    with connection.cursor() as cursor:
        found = migration.violations(cursor)
        assert [number for number, _ in found] == ["RF-OLD-1", "RF-OLD-2"]
        with pytest.raises(RuntimeError) as exc:
            migration.verify_refunds_fit(cursor)
    message = str(exc.value)
    assert "RF-OLD-1" in message
    assert "RF-OLD-2" in message
    assert "ADR 0024" in message
    # Nothing was rewritten.
    assert Refund.objects.get(number="RF-OLD-2").method == "bank_transfer"
    assert Refund.objects.get(number="RF-OLD-1").credit_note_id is None
