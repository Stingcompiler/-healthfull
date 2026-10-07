"""Seed the fixed role set (ARCHITECTURE 4.10) and the CenterProfile / Policy singletons.

The role list is a frozen copy: migrations must not import app code that can change.
``apps/core/tests/test_roles.py`` asserts it matches ``apps.core.roles.ROLES``.
"""

from django.db import migrations

ROLES = [
    ("receptionist", "موظف استقبال", "Receptionist"),
    ("doctor", "طبيب", "Doctor"),
    ("cashier", "كاشير", "Cashier"),
    ("cashier_supervisor", "مشرف الكاشير", "Cashier supervisor"),
    ("pharmacist", "صيدلي", "Pharmacist"),
    ("lab_tech", "فني معمل", "Lab technician"),
    ("lab_supervisor", "مشرف المعمل", "Lab supervisor"),
    ("nurse", "ممرض", "Nurse"),
    ("accountant", "محاسب", "Accountant"),
    ("manager", "مدير", "Manager"),
    ("admin", "مدير النظام", "System administrator"),
]


def seed(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    for code, name_ar, name_en in ROLES:
        Role.objects.update_or_create(code=code, defaults={"name_ar": name_ar, "name_en": name_en})
    apps.get_model("core", "CenterProfile").objects.get_or_create(pk=1)
    apps.get_model("core", "Policy").objects.get_or_create(pk=1)


def unseed(apps, schema_editor):
    # Roles may be referenced by users; leave data in place when migrating backwards.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
