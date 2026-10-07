"""Add the CASH_SAFE account: cash outside the drawers (ADR 0006).

The opening float leaves the safe, handovers to the safe, a supervisor or the next shift sit
here until received, and a closed shift's counted cash is swept here, so a shift's CASH
balance is always its drawer. A frozen copy of the row; ``apps/ledger/tests/test_models.py``
checks that ``0003_seed_accounts.CHART`` plus ``ADDED`` equals ``apps.ledger.chart.CHART``.
"""

from django.db import migrations

ADDED = [
    ('CASH_SAFE', 'نقد في الخزنة أو قيد التسليم', 'Cash in safe or in transit', 'asset', 'debit'),
]


def seed(apps, schema_editor):
    Account = apps.get_model("ledger", "Account")
    base = Account.objects.count()
    for order, (code, name_ar, name_en, kind, normal_balance) in enumerate(ADDED, start=base):
        Account.objects.get_or_create(
            code=code,
            defaults={
                "name_ar": name_ar,
                "name_en": name_en,
                "kind": kind,
                "normal_balance": normal_balance,
                "sort_order": order,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0004_remove_journalentry_ledger_entry_source_type_valid_and_more"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
