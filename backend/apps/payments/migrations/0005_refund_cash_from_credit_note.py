"""Refunds: cash only, from a credit note (ADR 0024, inspection F08).

The service has only ever written cash refunds with a credit note; the schema also allowed
``bank_transfer`` and a refund sourced by a service line alone. Before the constraints are
narrowed, ``verify_refunds_fit`` lists every existing row that would break them and stops
the migration with their numbers. It never rewrites data: an operator decides what to do
with such a row (docs/adr/0024-refunds-cash-from-a-credit-note.md).
"""

from typing import Any

from django.conf import settings
from django.db import migrations, models

_VIOLATIONS_SQL = """
    SELECT number,
           concat_ws(', ',
               CASE WHEN credit_note_id IS NULL THEN 'no credit note' END,
               CASE WHEN method <> 'cash' THEN 'method ' || method END,
               CASE WHEN bank_id IS NOT NULL THEN 'bank set' END,
               CASE WHEN reference <> '' THEN 'reference set' END)
      FROM payments_refund
     WHERE credit_note_id IS NULL OR method <> 'cash' OR bank_id IS NOT NULL OR reference <> ''
     ORDER BY number
"""


def violations(cursor: Any) -> list[tuple[str, str]]:
    """(refund number, what does not fit) for every row the new constraints would refuse."""
    cursor.execute(_VIOLATIONS_SQL)
    return [(number, problem) for number, problem in cursor.fetchall()]


def verify_refunds_fit(cursor: Any) -> None:
    found = violations(cursor)
    if found:
        listed = "; ".join(f"{number} ({problem})" for number, problem in found[:50])
        more = f" and {len(found) - 50} more" if len(found) > 50 else ""
        raise RuntimeError(
            f"payments 0005: {len(found)} refund(s) do not fit the narrowed schema (cash only,"
            f" from a credit note; ADR 0024): {listed}{more}. Nothing was changed. Decide what"
            " to do with these rows (docs/adr/0024-refunds-cash-from-a-credit-note.md), then"
            " run the migration again."
        )


def _verify(apps: Any, schema_editor: Any) -> None:
    with schema_editor.connection.cursor() as cursor:
        verify_refunds_fit(cursor)



class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0004_remove_creditnote_credit_note_consistent_and_more'),
        ('core', '0017_center_page'),
        ('orders', '0004_line_guard_void_admission_nights'),
        ('patients', '0002_patientmerge_reason'),
        ('payments', '0004_remove_cashhandover_shift_must_be_open_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # First, and in the same transaction: stop before any change if a row does not fit.
        migrations.RunPython(_verify, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name='refund',
            name='payments_refund_method_valid',
        ),
        migrations.RemoveConstraint(
            model_name='refund',
            name='payments_refund_has_source',
        ),
        migrations.RemoveConstraint(
            model_name='refund',
            name='payments_refund_transfer_has_bank',
        ),
        migrations.AlterField(
            model_name='refund',
            name='method',
            field=models.CharField(choices=[('cash', 'Cash')], default='cash', max_length=20),
        ),
        migrations.AlterField(
            model_name='refundevent',
            name='method',
            field=models.CharField(choices=[('cash', 'Cash')], default='cash', max_length=20),
        ),
        migrations.AddConstraint(
            model_name='refund',
            constraint=models.CheckConstraint(condition=models.Q(('method__in', ['cash'])), name='payments_refund_method_valid'),
        ),
        migrations.AddConstraint(
            model_name='refund',
            constraint=models.CheckConstraint(condition=models.Q(('credit_note__isnull', False)), name='payments_refund_from_credit_note'),
        ),
        migrations.AddConstraint(
            model_name='refund',
            constraint=models.CheckConstraint(condition=models.Q(('bank__isnull', True), ('method', 'cash'), ('reference', '')), name='payments_refund_cash_only'),
        ),
    ]
