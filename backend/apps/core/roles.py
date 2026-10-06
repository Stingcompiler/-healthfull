"""The fixed set of roles (ARCHITECTURE 4.10, FEATURES 0.2).

Rows in ``core.Role`` are created by migration ``0002_seed_roles`` from a frozen copy of
this list; ``test_roles_match_migration`` keeps the two in sync.
"""

from __future__ import annotations

from dataclasses import dataclass

RECEPTIONIST = "receptionist"
DOCTOR = "doctor"
CASHIER = "cashier"
CASHIER_SUPERVISOR = "cashier_supervisor"
PHARMACIST = "pharmacist"
LAB_TECH = "lab_tech"
LAB_SUPERVISOR = "lab_supervisor"
NURSE = "nurse"
ACCOUNTANT = "accountant"
MANAGER = "manager"
ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class RoleDef:
    code: str
    name_ar: str
    name_en: str


ROLES: tuple[RoleDef, ...] = (
    RoleDef(RECEPTIONIST, "موظف استقبال", "Receptionist"),
    RoleDef(DOCTOR, "طبيب", "Doctor"),
    RoleDef(CASHIER, "كاشير", "Cashier"),
    RoleDef(CASHIER_SUPERVISOR, "مشرف الكاشير", "Cashier supervisor"),
    RoleDef(PHARMACIST, "صيدلي", "Pharmacist"),
    RoleDef(LAB_TECH, "فني معمل", "Lab technician"),
    RoleDef(LAB_SUPERVISOR, "مشرف المعمل", "Lab supervisor"),
    RoleDef(NURSE, "ممرض", "Nurse"),
    RoleDef(ACCOUNTANT, "محاسب", "Accountant"),
    RoleDef(MANAGER, "مدير", "Manager"),
    RoleDef(ADMIN, "مدير النظام", "System administrator"),
)

ROLE_CODES: frozenset[str] = frozenset(r.code for r in ROLES)
