"""Call a stock batch "التشغيلة" in the batch-override reason (PROGRESS: terminology).

"الدفعة" also means a payment. The seed (core 0007) now writes the new label; this renames
the row of databases seeded before, only while it still carries the old default text, so a
center's own wording is kept.
"""

from django.db import migrations

OLD = "اختيار دفعة أخرى"
NEW = "اختيار تشغيلة أخرى"


def rename(apps, schema_editor):
    ReasonCode = apps.get_model("core", "ReasonCode")
    ReasonCode.objects.filter(category="override", code="BATCH_CHOICE", label_ar=OLD).update(
        label_ar=NEW
    )


def restore(apps, schema_editor):
    ReasonCode = apps.get_model("core", "ReasonCode")
    ReasonCode.objects.filter(category="override", code="BATCH_CHOICE", label_ar=NEW).update(
        label_ar=OLD
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_merge_wave_a_admin_patients"),
        ("pharmacy", "0003_dispensereturn_remove_stocktransfer_insert_insert_and_more"),
    ]

    operations = [migrations.RunPython(rename, restore)]
