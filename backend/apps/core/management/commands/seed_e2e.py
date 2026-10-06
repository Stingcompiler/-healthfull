"""Idempotent seed for end-to-end tests (ARCHITECTURE 6).

Creates the center profile, policy singleton, departments and one user per role. Safe to
run repeatedly: existing rows are updated back to the seed values, so lockouts or
preference changes made by a previous e2e run are reset.

The password below is a TEST VALUE ONLY. It also appears in ``e2e/fixtures/users.ts`` and
nowhere else. This command refuses to run when DEBUG is off unless ``ALLOW_SEED_E2E=1``,
so it cannot plant known credentials on a production server by accident.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import pghistory
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core import roles
from apps.core.models import (
    CenterProfile,
    Department,
    DoctorProfile,
    Language,
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
)

DEPARTMENTS: tuple[tuple[str, str, str], ...] = (
    ("GEN", "الطب العام", "General Medicine"),
    ("PED", "طب الأطفال", "Pediatrics"),
    ("GYN", "النساء والتوليد", "Gynecology"),
    ("DEN", "الأسنان", "Dental"),
    ("LAB", "المعمل", "Laboratory"),
    ("PHA", "الصيدلية", "Pharmacy"),
)

CENTER = {
    "name_ar": "مركز النيل الطبي (تجريبي)",
    "name_en": "Nile Medical Center (test)",
    "address": "الخرطوم، السودان",
    "phone": "+249 900 000 000",
    "registration_no": "TEST-0001",
}


class Command(BaseCommand):
    help = "Seed the e2e dataset (center, policy, departments, one user per role). Idempotent."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG and os.environ.get("ALLOW_SEED_E2E") != "1":
            raise CommandError(
                "Refusing to seed e2e users with DEBUG off. Set ALLOW_SEED_E2E=1 if this "
                "really is a test database."
            )
        with transaction.atomic(), pghistory.context(command="seed_e2e"):
            self._seed_roles()
            self._seed_center()
            departments = self._seed_departments()
            created = self._seed_users(departments["GEN"])
        self.stdout.write(
            self.style.SUCCESS(
                f"seed_e2e: {len(USERS)} users ({created} new), {len(DEPARTMENTS)} departments, "
                f"center profile and policy ready."
            )
        )

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

    def _seed_departments(self) -> dict[str, Department]:
        result: dict[str, Department] = {}
        for order, (code, name_ar, name_en) in enumerate(DEPARTMENTS, start=1):
            dept, _ = Department.objects.update_or_create(
                code=code,
                defaults={
                    "name_ar": name_ar,
                    "name_en": name_en,
                    "active": True,
                    "sort_order": order,
                },
            )
            result[code] = dept
        return result

    def _seed_users(self, doctor_department: Department) -> int:
        created_count = 0
        role_by_code = {r.code: r for r in Role.objects.all()}
        for spec in USERS:
            is_admin = spec.role == roles.ADMIN
            user, created = User.objects.update_or_create(
                username=spec.username,
                defaults={
                    "full_name_ar": spec.full_name_ar,
                    "full_name_en": spec.full_name_en,
                    "email": f"{spec.username}@example.test",
                    "is_active": True,
                    "is_staff": is_admin,
                    "is_superuser": is_admin,
                    "must_change_password": False,
                    "failed_login_count": 0,
                    "locked_until": None,
                    # Specs change these through the preferences API; start every run clean.
                    "language": Language.AR,
                    "theme": Theme.LIGHT,
                },
            )
            created_count += int(created)
            if created or not user.check_password(E2E_PASSWORD):
                user.set_password(E2E_PASSWORD)
                user.save(update_fields=["password", "password_changed_at"])
            # Exactly the seeded role, nothing else.
            UserRole.objects.filter(user=user).exclude(role__code=spec.role).delete()
            UserRole.objects.get_or_create(user=user, role=role_by_code[spec.role])
            if spec.role == roles.DOCTOR:
                DoctorProfile.objects.update_or_create(
                    user=user,
                    defaults={
                        "department": doctor_department,
                        "specialty_ar": "طب عام",
                        "specialty_en": "General practice",
                        "active": True,
                    },
                )
        return created_count
