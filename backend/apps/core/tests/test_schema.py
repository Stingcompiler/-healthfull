"""Cross-app schema guarantees: history tracking, protection triggers, admin coverage."""

from __future__ import annotations

from typing import Any

import pytest
from django.apps import apps
from django.contrib import admin
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db

MODULE_APPS = [
    "core",
    "catalog",
    "patients",
    "visits",
    "orders",
    "clinical",
    "billing",
    "payments",
    "ledger",
    "pharmacy",
    "lab",
    "claims",
    "portal",
    "imports",
    "ops",
]

#: Rows that never change once written: protected by an append-only trigger, so no history.
APPEND_ONLY = {
    ("core", "AuthEvent"),
    ("patients", "PatientMerge"),
    ("payments", "ShiftReview"),
    ("payments", "Allocation"),
    ("ledger", "JournalEntry"),
    ("ledger", "JournalLine"),
    ("pharmacy", "StockMove"),
    ("pharmacy", "Dispense"),
    ("pharmacy", "DispenseLine"),
    ("pharmacy", "DispenseReturn"),
    ("claims", "PayerPaymentAllocation"),
}

#: Mutable but deliberately untracked (documented reason in each model's docstring/comment).
UNTRACKED = {
    ("core", "Sequence"),  # counters; documents carry their numbers
    ("core", "Notification"),
    ("core", "LoginThrottle"),
    ("pharmacy", "StockBalance"),  # projection of StockMove, written only by its trigger
    ("imports", "ImportRow"),  # bulk staging rows of a tracked ImportJob
}

#: (table, trigger name) that ARCHITECTURE 4.9 and invariants 1, 3, 5 rely on.
PROTECTION_TRIGGERS = [
    ("billing_invoice", "invoice_frozen"),
    ("billing_invoice", "invoice_consistent"),
    ("billing_invoiceline", "line_frozen"),
    ("billing_invoiceline", "line_needs_draft_invoice"),
    ("billing_creditnote", "credit_note_frozen"),
    ("billing_creditnote", "credit_note_consistent"),
    ("billing_creditnoteline", "line_frozen"),
    ("payments_shift", "shift_closed"),
    ("payments_payment", "shift_must_be_open"),
    ("payments_payment", "payment_money_readonly"),
    ("payments_payment", "payment_no_delete"),
    ("payments_refund", "shift_must_be_open"),
    ("payments_cashhandover", "shift_must_be_open"),
    ("payments_allocation", "append_only"),
    ("ledger_journalentry", "append_only"),
    ("ledger_journalentry", "entry_balanced"),
    ("ledger_journalline", "append_only"),
    ("ledger_journalline", "line_entry_balanced"),
    ("pharmacy_stockmove", "append_only"),
    ("pharmacy_stockmove", "stock_balance"),
    ("lab_resultversion", "result_version_guard"),
    ("lab_resultvalue", "value_needs_draft_version"),
    ("orders_serviceline", "line_guard"),
    # Phase 1 review fixes: a line never moves to another document (invariant 2) ...
    ("billing_invoiceline", "line_parent_fixed"),
    ("billing_creditnoteline", "line_parent_fixed"),
    # ... nothing is booked into a closed shift and its handovers never change (invariant 3)
    ("payments_allocation", "shift_must_be_open"),
    ("ledger_journalentry", "shift_must_be_open"),
    ("ledger_journalline", "shift_must_be_open"),
    ("payments_cashhandover", "handover_guard"),
    # ... decisions stay recorded (invariant 4) ...
    ("payments_payment", "payment_verification_forward"),
    ("payments_refund", "refund_request_readonly"),
    ("payments_refund", "refund_forward"),
    ("orders_performauthorization", "authorization_guard"),
    ("claims_claimline", "claim_line_guard"),
    # ... stock leaves only for paid or authorized, still billed units (invariants 1 and 5)
    ("pharmacy_dispenseline", "dispense_line_eligible"),
    # ... frozen prices keep their version (invariant 6) ...
    ("catalog_pricelistversion", "version_guard"),
    ("catalog_priceitem", "item_guard"),
    # ... and protected tables are never truncated by the application role.
    ("billing_invoice", "truncate_guard"),
    ("payments_payment", "truncate_guard"),
    ("payments_allocation", "truncate_guard"),
    ("ledger_journalline", "truncate_guard"),
    ("pharmacy_stockmove", "truncate_guard"),
    ("orders_serviceline", "truncate_guard"),
]


def _module_models() -> list[Any]:
    return [
        m
        for label in MODULE_APPS
        for m in apps.get_app_config(label).get_models()
        if not m.__name__.endswith("Event") and m._meta.app_label == label
    ]


def test_every_mutable_model_is_history_tracked() -> None:
    missing = []
    for model in _module_models():
        key = (model._meta.app_label, model.__name__)
        has_event = any(
            m.__name__ == f"{model.__name__}Event" for m in apps.get_app_config(key[0]).get_models()
        )
        if key in APPEND_ONLY:
            assert not has_event, f"{key} is append-only and must not be tracked"
        elif key not in UNTRACKED and not model._meta.auto_created and not has_event:
            missing.append(key)
    assert missing == []


def test_protection_triggers_are_installed() -> None:
    from apps.core.tests.builders import sql

    installed = {
        (table, name)
        for table, name in sql(
            "SELECT c.relname, t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE NOT t.tgisinternal AND t.tgname LIKE 'pgtrigger_%%'"
        )
    }
    found = {
        (table, name.removeprefix("pgtrigger_").rsplit("_", 1)[0]) for table, name in installed
    }
    assert [t for t in PROTECTION_TRIGGERS if t not in found] == []


#: Phase 0 models edited elsewhere: role links and overrides as inlines of User and Role,
#: login throttles only through login bookkeeping and the audited unlock action (ADR 0005).
ADMIN_EXEMPT = {"core.UserRole", "core.RolePermission", "core.LoginThrottle"}


def test_every_model_is_registered_in_admin() -> None:
    registered = set(admin.site._registry)
    missing = [
        f"{m._meta.app_label}.{m.__name__}"
        for m in _module_models()
        if m not in registered and not m._meta.auto_created
    ]
    assert sorted(set(missing) - ADMIN_EXEMPT) == []


@pytest.fixture
def superuser_client(make_user: Any) -> Client:
    client = Client()
    client.force_login(make_user("schema_root", is_superuser=True, is_staff=True))
    return client


def test_every_changelist_and_add_page_renders(superuser_client: Client) -> None:
    for model in _module_models():
        if model not in admin.site._registry:
            continue
        info = (model._meta.app_label, model._meta.model_name)
        url = reverse("admin:{}_{}_changelist".format(*info))
        assert superuser_client.get(url).status_code == 200, url
        add = superuser_client.get(reverse("admin:{}_{}_add".format(*info)))
        assert add.status_code in (200, 403), url


def test_protected_documents_are_read_only_in_admin(superuser_client: Client) -> None:
    from apps.core.tests import builders as b

    inv = b.approved_invoice()
    sh = b.close_shift(b.shift())
    for obj in (inv, sh, inv.lines.get()):
        url = reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change", args=[obj.pk])
        assert superuser_client.get(url).status_code == 200
        assert superuser_client.post(url, {}).status_code == 403
        add = reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_add")
        assert superuser_client.get(add).status_code == 403
