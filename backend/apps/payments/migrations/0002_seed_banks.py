"""Seed common Sudanese banks and wallets for transfer payments (FEATURES 6.1).

Editable reference data: a center deactivates or adds banks in the administration screens.
"""

from django.db import migrations

BANKS = [
    ("BOK", "بنك الخرطوم (بنكك)", "Bank of Khartoum (Bankak)"),
    ("FIB", "بنك فيصل الإسلامي (فوري)", "Faisal Islamic Bank (Fawry)"),
    ("ONB", "بنك أمدرمان الوطني (أوكاش)", "Omdurman National Bank (O-Cash)"),
    ("OTHER", "بنك آخر", "Other bank"),
]


def seed(apps, schema_editor):
    Bank = apps.get_model("payments", "Bank")
    for order, (code, name_ar, name_en) in enumerate(BANKS):
        Bank.objects.get_or_create(
            code=code, defaults={"name_ar": name_ar, "name_en": name_en, "sort_order": order}
        )


def unseed(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
