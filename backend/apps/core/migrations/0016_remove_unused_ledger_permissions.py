"""Remove the matrix rows of two permission codes that guarded nothing.

``ledger.view`` and ``ledger.manage_accounts`` were registered in Phase 1 but no endpoint or
screen ever used them (the ledger's figures reach people through the reports, and the chart
of accounts is fixed in code). Phase 8 removed the codes from the registry; this deletes any
``RolePermission`` override an administrator saved for them, so the matrix holds registered
codes only (``RolePermission.clean`` refuses unknown codes). Reversing restores nothing: the
codes no longer exist.
"""

from django.db import migrations

REMOVED = ("ledger.view", "ledger.manage_accounts")


def forwards(apps, schema_editor):
    RolePermission = apps.get_model("core", "RolePermission")
    RolePermission.objects.filter(code__in=REMOVED).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0015_claims_second_approver_policy"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
