"""Seed the default cash price list (FEATURES 5.2).

Lines billed to the patient, and payers without a contract list, are priced from the default
cash list; its dated versions are created by the administrator or a price import.
"""

from django.db import migrations


def seed(apps, schema_editor):
    PriceList = apps.get_model("catalog", "PriceList")
    if not PriceList.objects.filter(is_default=True).exists():
        PriceList.objects.get_or_create(
            code="CASH",
            defaults={
                "name_ar": "قائمة أسعار النقد",
                "name_en": "Cash price list",
                "kind": "cash",
                "is_default": True,
                "active": True,
            },
        )


def unseed(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
