"""Every notification links only to screens its recipients may open (FEATURES 0.13).

Recipients and links live in ``apps.core.notification_kinds``. For every kind and every role
that receives it by default, at least one of its links needs a permission that role holds by
default; the bell opens the first such link (frontend ``kinds.ts``, whose contract test reads
the same table). A manager's "transfer rejected" once linked only to the transfer queue, whose
endpoints need ``payments.confirm_transfer``, which managers do not hold.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from apps.core.models import Notification
from apps.core.notification_kinds import KINDS, NotificationKind
from apps.core.permissions import PERMISSIONS
from apps.core.roles import ROLE_CODES

APPS = Path(__file__).resolve().parents[2]


def _defaults(code: str) -> frozenset[str]:
    return PERMISSIONS[code].default_roles


def _recipient_roles(spec: NotificationKind) -> frozenset[str]:
    roles = set(spec.roles)
    for code in (spec.holders_of, spec.users_holding):
        if code:
            roles |= _defaults(code)
    return frozenset(roles)


@pytest.mark.parametrize("code", sorted(KINDS))
def test_every_recipient_may_open_a_link_of_its_kind(code: str) -> None:
    spec = KINDS[code]
    assert spec.links, code
    recipients = _recipient_roles(spec)
    assert recipients, f"{code} names no recipient"
    assert recipients <= ROLE_CODES
    for link in spec.links:
        assert link.permission in PERMISSIONS, (code, link.permission)
        assert link.route.startswith("/"), (code, link.route)
    for role in sorted(recipients):
        opens = [link.route for link in spec.links if role in _defaults(link.permission)]
        assert opens, f"{code}: role {role} receives it but may open none of its screens"


def test_the_manager_reads_a_rejected_transfer_on_the_patient_file() -> None:
    spec = KINDS["transfer_rejected"]
    assert "manager" in _recipient_roles(spec)
    first_for_manager = next(link for link in spec.links if "manager" in _defaults(link.permission))
    assert first_for_manager.route == "/patients/$patientId"


def _created_kinds() -> set[str]:
    """String kinds passed to notify_users / notify_roles / notify_kind in the app code."""
    found: set[str] = set()
    for path in APPS.rglob("*.py"):
        if "tests" in path.parts or "migrations" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            position = {"notify_kind": 0, "notify_users": 1, "notify_roles": 1}.get(str(name))
            if position is None or len(node.args) <= position:
                continue
            arg = node.args[position]
            # A name: `kind = "a" if x else "b"` just before the call.
            named = isinstance(arg, ast.Name)
            found |= _assigned_strings(tree, arg.id) if named else _strings(arg)  # type: ignore[attr-defined]
    return found


def _strings(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _strings(node.body) | _strings(node.orelse)
    return set()


def _assigned_strings(tree: ast.AST, name: str) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            out |= _strings(node.value)
    return out


def test_every_kind_the_code_sends_is_registered() -> None:
    sent = _created_kinds()
    assert {"lab_result_ready", "lab_result_critical", "transfer_rejected"} <= sent
    assert sent - set(KINDS) == set()


@pytest.mark.django_db
def test_notify_kind_reaches_the_registered_recipients(make_user: Any) -> None:
    from apps.core.services import notify_kind

    manager = make_user("nk-mgr", roles=["manager"])
    supervisor = make_user("nk-sup", roles=["cashier_supervisor"])
    make_user("nk-cash", roles=["cashier"])
    admin = make_user("nk-admin", roles=["admin"])
    assert notify_kind("transfer_rejected", payment_id=1, patient_id=2) == 2
    got = set(Notification.objects.filter(kind="transfer_rejected").values_list("user", flat=True))
    assert got == {manager.pk, supervisor.pk}
    assert notify_kind("integrity_failed", failed=["ledger_balanced"]) == 2
    got = set(Notification.objects.filter(kind="integrity_failed").values_list("user", flat=True))
    assert got == {manager.pk, admin.pk}
    with pytest.raises(ValueError, match="notify_users"):
        notify_kind("lab_result_ready", visit_id=1)
