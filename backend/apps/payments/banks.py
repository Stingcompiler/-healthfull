"""The banks and wallets transfers arrive through (FEATURES 6.1): the administration list.

Guarded by ``payments.manage_banks`` at the router. A transfer, QR or card payment names a bank
by code, and its reference is unique per bank (FEATURES 6.2), so a bank's code never changes
and a bank is never deleted: a center deactivates it, which takes it off the cashier's list
(``queries.banks``; ``services.take_payment`` refuses it with ``BANK_INACTIVE``) while its
payments keep pointing at it. Every write records who and why (pghistory).
"""

from __future__ import annotations

import re
from typing import Any

import pghistory
from django.db import transaction
from django.db.models import QuerySet

from apps.core.models import User
from apps.payments.models import Bank
from domain.errors import DomainError

__all__ = ["create_bank", "list_banks", "update_bank"]

_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_-]{0,19}\Z")
_EDITABLE = frozenset({"name_ar", "name_en", "active", "sort_order"})


def list_banks() -> QuerySet[Bank]:
    """Every bank, active or not, in the cashier's order."""
    return Bank.objects.order_by("sort_order", "code")


def create_bank(
    actor: User,
    *,
    code: str,
    name_ar: str,
    name_en: str,
    active: bool = True,
    sort_order: int = 0,
) -> Bank:
    """Add a bank or wallet.

    Raises:
        DomainError: ``INVALID_CODE`` (upper-case letters, digits, ``-`` and ``_``, starting
            with a letter), ``BANK_CODE_TAKEN``.
    """
    value = (code or "").strip()
    if not _CODE_RE.match(value):
        raise DomainError(
            "INVALID_CODE",
            "Codes use upper-case letters, digits, '-' and '_' and start with a letter",
            value=value,
        )
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="create bank"):
        if Bank.objects.filter(code__iexact=value).exists():
            raise DomainError("BANK_CODE_TAKEN", "This bank code exists", value=value)
        return Bank.objects.create(
            code=value,
            name_ar=name_ar.strip(),
            name_en=name_en.strip(),
            active=active,
            sort_order=sort_order,
        )


def update_bank(actor: User, bank_id: int, **fields: Any) -> Bank:
    """Rename, reorder or (de)activate a bank; its code never changes.

    Raises:
        ValueError: a field that is not editable (the code).
        Bank.DoesNotExist: no such bank (HTTP 404).
    """
    unknown = set(fields) - _EDITABLE
    if unknown:
        raise ValueError(f"Not editable bank fields: {sorted(unknown)}")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="edit bank"):
        bank = Bank.objects.select_for_update().get(pk=bank_id)
        for attr, value in fields.items():
            setattr(bank, attr, value.strip() if isinstance(value, str) else value)
        bank.save()
    return bank
