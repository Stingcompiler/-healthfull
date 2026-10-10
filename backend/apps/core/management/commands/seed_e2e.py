"""Idempotent seed for end-to-end tests (ARCHITECTURE 6).

Creates the center profile, policy singleton, departments, one user per role, three more
doctor accounts, a separate break-glass superuser (``root``) and the base catalog
(``apps.core.e2e.catalog``: doctors' schedules, services, price lists, payers and coverage,
stock, lab tests, wards and beds, tills, reason codes). Safe to run repeatedly: existing rows
are updated back to the seed values, so lockouts, login throttles or preference changes made
by a previous e2e run are reset, and dated or posted documents are never created twice.

The role users hold exactly their role and nothing more; in particular ``admin`` is a
normal user with the admin role (not a superuser), so e2e exercises the admin role's real
permission defaults and overrides. Only ``root`` is a superuser.

The password below is a TEST VALUE ONLY. It also appears in ``e2e/fixtures/users.ts`` and
nowhere else. The command resets existing accounts to that known password, so it runs only
when DEBUG is on AND the database is a test one (name starting ``e2e_`` or ``test_``), or
when ``ALLOW_SEED_E2E=1`` says so explicitly (``make seed`` on the dev database); see
``apps.core.e2e.guard``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pghistory
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core import roles
from apps.core.e2e.catalog import DEPARTMENTS, EXTRA_DOCTORS, GENERAL_DOCTOR, seed_catalog
from apps.core.e2e.catalog import seed_departments as _seed_departments
from apps.core.e2e.guard import TEST_DB_NAME, require_test_database
from apps.core.models import (
    CenterProfile,
    Language,
    LoginThrottle,
    Policy,
    Role,
    Theme,
    User,
    UserRole,
)

E2E_PASSWORD = "Test-Pass-2026"  # noqa: S105 - test value, see module docstring


@dataclass(frozen=True)
class SeedUser:
    username: str
    role: str
    full_name_ar: str
    full_name_en: str


USERS: tuple[SeedUser, ...] = (
    SeedUser("reception", roles.RECEPTIONIST, "سارة عبدالله", "Sara Abdalla"),
    SeedUser("doctor", roles.DOCTOR, "د. أحمد الطيب", "Dr. Ahmed Altayeb"),
    SeedUser("cashier", roles.CASHIER, "محمد عثمان", "Mohamed Osman"),
    SeedUser("cashsup", roles.CASHIER_SUPERVISOR, "هالة إبراهيم", "Hala Ibrahim"),
    SeedUser("pharmacist", roles.PHARMACIST, "عمر الفاتح", "Omer Alfatih"),
    SeedUser("labtech", roles.LAB_TECH, "منى حسن", "Muna Hassan"),
    SeedUser("labsup", roles.LAB_SUPERVISOR, "خالد بشير", "Khalid Bashir"),
    SeedUser("nurse", roles.NURSE, "آمنة يوسف", "Amna Yousif"),
    SeedUser("accountant", roles.ACCOUNTANT, "طارق الأمين", "Tarig Alamin"),
    SeedUser("manager", roles.MANAGER, "نادية محمود", "Nadia Mahmoud"),
    SeedUser("admin", roles.ADMIN, "مدير النظام", "System Admin"),
    SeedUser("display", roles.DISPLAY, "شاشة الانتظار", "Waiting-room screen"),
)

#: More doctors (role ``doctor``, same test password) for the clinic screens; their profiles
#: and schedules come from ``apps.core.e2e.catalog.EXTRA_DOCTORS``.
DOCTOR_USERS: tuple[SeedUser, ...] = tuple(
    SeedUser(d.username, roles.DOCTOR, d.full_name_ar, d.full_name_en) for d in EXTRA_DOCTORS
)

#: Break-glass superuser (every permission). Kept apart from the role users above.
SUPERUSER = SeedUser("root", "", "حساب الطوارئ", "Break-glass superuser")

__all__ = [
    "DEPARTMENTS",
    "DOCTOR_USERS",
    "E2E_PASSWORD",
    "SUPERUSER",
    "TEST_DB_NAME",
    "USERS",
    "Command",
]

CENTER = {
    "name_ar": "مركز النيل الطبي (تجريبي)",
    "name_en": "Nile Medical Center (test)",
    "address": "الخرطوم، السودان",
    "phone": "+249 900 000 000",
    "registration_no": "TEST-0001",
}


class Command(BaseCommand):
    help = (
        "Seed the e2e dataset (center, policy, one user per role, more doctors, base catalog). "
        "Idempotent."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        require_test_database("seed_e2e")
        with transaction.atomic(), pghistory.context(command="seed_e2e"):
            self._seed_roles()
            self._seed_center()
            departments = _seed_departments()
            created = self._seed_users()
            doctors_created = self._seed_doctor_users()
            self._seed_superuser()
            doctors = {
                u.username: u
                for u in User.objects.filter(
                    username__in=[d.username for d in (GENERAL_DOCTOR, *EXTRA_DOCTORS)]
                )
            }
            catalog = seed_catalog(
                actor=User.objects.get(username="admin"),
                doctors=doctors,
                departments=departments,
            )
            # Lockout/throttle state of unknown usernames and client addresses.
            LoginThrottle.objects.all().delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"seed_e2e: {len(USERS)} users ({created} new), {len(DOCTOR_USERS)} more doctors "
                f"({doctors_created} new), break-glass superuser {SUPERUSER.username!r}, "
                f"{len(DEPARTMENTS)} departments, center profile and policy ready. Catalog: "
                f"{catalog.services} services, {catalog.price_lists} price lists "
                f"({catalog.created_versions} new versions), {catalog.payers} payers, "
                f"{catalog.items} stock items ({catalog.created_receipts} new receipts), "
                f"{catalog.lab_tests} lab tests, {catalog.beds} beds."
            )
        )
        for note in catalog.notes:
            self.stdout.write(self.style.WARNING(f"seed_e2e: {note}"))

    def _seed_roles(self) -> None:
        for r in roles.ROLES:
            Role.objects.update_or_create(
                code=r.code, defaults={"name_ar": r.name_ar, "name_en": r.name_en}
            )

    def _seed_center(self) -> None:
        center = CenterProfile.load()
        changed = [k for k, v in CENTER.items() if getattr(center, k) != v]
        for key in changed:
            setattr(center, key, CENTER[key])
        if changed:
            center.save()
        Policy.load()

    def _seed_users(self) -> int:
        return self._seed_role_users(USERS)

    def _seed_doctor_users(self) -> int:
        """The extra doctor accounts; their clinic profiles come with the catalog."""
        return self._seed_role_users(DOCTOR_USERS)

    def _seed_role_users(self, specs: tuple[SeedUser, ...]) -> int:
        created_count = 0
        role_by_code = {r.code: r for r in Role.objects.all()}
        for spec in specs:
            user, created = self._upsert_user(spec, superuser=False)
            created_count += int(created)
            # Exactly the seeded role, nothing else.
            UserRole.objects.filter(user=user).exclude(role__code=spec.role).delete()
            UserRole.objects.get_or_create(user=user, role=role_by_code[spec.role])
        return created_count

    def _seed_superuser(self) -> None:
        user, _ = self._upsert_user(SUPERUSER, superuser=True)
        UserRole.objects.filter(user=user).delete()  # holds everything through is_superuser

    def _upsert_user(self, spec: SeedUser, *, superuser: bool) -> tuple[User, bool]:
        user, created = User.objects.update_or_create(
            username=spec.username,
            defaults={
                "full_name_ar": spec.full_name_ar,
                "full_name_en": spec.full_name_en,
                "email": f"{spec.username}@example.test",
                "is_active": True,
                # Only the break-glass account uses the Django admin site.
                "is_staff": superuser,
                "is_superuser": superuser,
                "must_change_password": False,
                "failed_login_count": 0,
                "locked_until": None,
                # Specs change these through the preferences API; start every run clean.
                "language": Language.AR,
                "theme": Theme.LIGHT,
            },
        )
        if created or not user.check_password(E2E_PASSWORD):
            user.set_password(E2E_PASSWORD)
            user.save(update_fields=["password", "password_changed_at"])
        return user, created
