"""Seed the public site settings row and carry the center page grant over (ADR 0029 B, K1).

1. ``PublicSiteSettings`` (one row). **New or existing install:** an install is *existing* when
   ``patients.Patient`` holds at least one row when this migration runs (a center that has
   registered a patient has data). This migration depends on the latest ``patients``
   migration, so the table always exists here, and a fresh install migrates an empty database
   before any seed command, so it always counts zero. A new install gets every switch off and
   approval on; an existing install keeps its portal and instant booking (tracking and booking
   on, approval off) and the website off. The four legacy booking rules take the values of
   their ``PORTAL_BOOKING_*`` settings (Django settings first, then the environment).
2. ``core.manage_public_site`` replaces ``core.manage_settings`` on the center page. Every role
   keeps exactly the access it had: a ``RolePermission`` row is written for the new code only
   where the role's effective ``core.manage_settings`` differs from the new code's default
   roles. Both codes default to ``{admin, manager}`` (hard-coded here: a historical migration
   never imports the live registry), so this copies the old code's override rows. Idempotent.
"""

from __future__ import annotations

import os
from typing import Any

from django.conf import settings
from django.db import migrations

from domain.public_site import LEGACY_ENV, initial_values

SOURCE_CODE = "core.manage_settings"
TARGET_CODE = "core.manage_public_site"
SOURCE_DEFAULT_ROLES = frozenset({"admin", "manager"})
TARGET_DEFAULT_ROLES = frozenset({"admin", "manager"})


def _legacy_env() -> dict[str, str]:
    found: dict[str, str] = {}
    for variable in LEGACY_ENV.values():
        value = getattr(settings, variable, None)
        if value is None:
            value = os.environ.get(variable)
        if value is not None:
            found[variable] = str(value)
    return found


def seed_settings(apps: Any, schema_editor: Any) -> None:
    settings_model = apps.get_model("core", "PublicSiteSettings")
    if settings_model.objects.filter(pk=1).exists():
        return
    existing = apps.get_model("patients", "Patient").objects.exists()
    settings_model.objects.create(
        pk=1, **initial_values(existing_install=existing, env=_legacy_env())
    )


def copy_grants(apps: Any, schema_editor: Any) -> None:
    """Give ``TARGET_CODE`` to exactly the roles that hold ``SOURCE_CODE`` (effective)."""
    role_model = apps.get_model("core", "Role")
    grant_model = apps.get_model("core", "RolePermission")
    source = dict(grant_model.objects.filter(code=SOURCE_CODE).values_list("role_id", "allowed"))
    for role in role_model.objects.all():
        holds = source.get(role.pk, role.code in SOURCE_DEFAULT_ROLES)
        if holds == (role.code in TARGET_DEFAULT_ROLES):
            grant_model.objects.filter(role=role, code=TARGET_CODE).delete()
            continue
        grant_model.objects.update_or_create(
            role=role, code=TARGET_CODE, defaults={"allowed": holds}
        )


def remove_grants(apps: Any, schema_editor: Any) -> None:
    apps.get_model("core", "RolePermission").objects.filter(code=TARGET_CODE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0019_public_site_settings"),
        ("patients", "0002_patientmerge_reason"),
    ]

    operations = [
        migrations.RunPython(seed_settings, migrations.RunPython.noop),
        migrations.RunPython(copy_grants, remove_grants),
    ]
