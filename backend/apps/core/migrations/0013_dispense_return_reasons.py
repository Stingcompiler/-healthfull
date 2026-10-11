"""Stock-adjustment reasons for dispense returns (FEATURES 8.4, invariant 4, ADR 0018).

A frozen copy of the matching rows of ``apps.core.reason_codes.REASON_CODES``
(``apps/core/tests/test_seeds.py`` keeps them in sync). Existing rows are left alone so a
center's edits survive.
"""

from django.db import migrations

REASON_CODES = [
    ('stock_adjust', 'PATIENT_RETURNED', 'أعاده المريض', 'Returned by the patient', False),
    ('stock_adjust', 'DISPENSED_IN_ERROR', 'صُرف بالخطأ', 'Dispensed in error', False),
]

# Sort orders continue after the codes seeded by 0007, 0009 and 0012.
FIRST_SORT_ORDER = 100


def seed(apps, schema_editor):
    ReasonCode = apps.get_model("core", "ReasonCode")
    for order, (category, code, label_ar, label_en, requires_note) in enumerate(REASON_CODES):
        ReasonCode.objects.get_or_create(
            category=category,
            code=code,
            defaults={
                "label_ar": label_ar,
                "label_en": label_en,
                "requires_note": requires_note,
                "sort_order": FIRST_SORT_ORDER + order,
            },
        )


def unseed(apps, schema_editor):
    # Reason codes are referenced by documents; leave them in place when migrating backwards.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_admission_cancel_reasons'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
