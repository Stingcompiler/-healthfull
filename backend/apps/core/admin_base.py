"""Shared Django admin bases for the module apps.

Business documents (invoices, payments, shifts, stock moves, results, journal...) are
written only through ``apps/<m>/services.py``, which apply the domain rules, locks, ledger
postings and audit context. Their admins are therefore view-only (``ReadOnlyAdmin``); the DB
triggers would refuse most edits anyway. Reference data (catalog, payers, items, tests...)
stays editable by the break-glass administrator.
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.db import models
from django.http import HttpRequest


class ReadOnlyAdmin[M: models.Model](admin.ModelAdmin[M]):
    """View-only admin: no add, change or delete."""

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


class ReadOnlyInline[M: models.Model, P: models.Model](admin.TabularInline[M, P]):
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
