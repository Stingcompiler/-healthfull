"""Seed the fixed chart of accounts (ARCHITECTURE 4.7).

A frozen copy of ``apps.ledger.chart.CHART``; ``apps/ledger/tests/test_models.py`` asserts the
two match.
"""

from django.db import migrations

CHART = [
    ('CASH', 'النقد في الصندوق', 'Cash in drawer', 'asset', 'debit'),
    ('BANK_PENDING', 'تحويلات بانتظار التحقق', 'Transfers awaiting verification', 'asset', 'debit'),
    ('BANK', 'البنك (مؤكد)', 'Bank (verified)', 'asset', 'debit'),
    ('AR_PATIENT', 'ذمم المرضى', 'Patient receivable', 'asset', 'debit'),
    ('AR_PAYER', 'ذمم جهات التغطية', 'Payer receivable', 'asset', 'debit'),
    ('PATIENT_CREDIT', 'أرصدة المرضى', 'Patient credit', 'liability', 'credit'),
    ('REVENUE', 'إيراد الخدمات', 'Service revenue', 'revenue', 'credit'),
    ('DISCOUNT', 'الخصومات والإعفاءات', 'Discounts', 'contra_revenue', 'debit'),
    ('WRITE_OFF', 'شطب مرفوضات جهات التغطية', 'Payer write-offs', 'expense', 'debit'),
    ('CASH_OVER_SHORT', 'فروق النقد', 'Cash over and short', 'expense', 'debit'),
]


def seed(apps, schema_editor):
    Account = apps.get_model("ledger", "Account")
    for order, (code, name_ar, name_en, kind, normal_balance) in enumerate(CHART):
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


def unseed(apps, schema_editor):
    # Accounts can never be deleted (trigger); nothing to undo.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
