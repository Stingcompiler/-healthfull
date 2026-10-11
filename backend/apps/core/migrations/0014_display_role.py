"""The twelfth role, ``display``: the waiting-room kiosk account (ADR 0019).

A frozen copy of the matching row of ``apps.core.roles.ROLES`` (``apps/core/tests/test_roles.py``
keeps it in sync). The role's only permission, ``visits.view_display``, is a registry default.
"""

from django.db import migrations

ROLES = [
    ("display", "شاشة الانتظار", "Waiting-room display"),
]


def seed(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    for code, name_ar, name_en in ROLES:
        Role.objects.update_or_create(code=code, defaults={"name_ar": name_ar, "name_en": name_en})


def unseed(apps, schema_editor):
    # Roles may be referenced by users; leave data in place when migrating backwards.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_dispense_return_reasons"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
