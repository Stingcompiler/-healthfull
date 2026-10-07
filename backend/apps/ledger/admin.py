from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from apps.core.admin_base import ReadOnlyAdmin, ReadOnlyInline
from apps.ledger.models import Account, JournalEntry, JournalLine


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin[Account]):
    """The chart is fixed: only the display names can change."""

    list_display = ("code", "name_ar", "name_en", "kind", "normal_balance", "active")
    readonly_fields = ("code", "kind", "normal_balance")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


class JournalLineInline(ReadOnlyInline[JournalLine, JournalEntry]):
    model = JournalLine
    fields = ("account", "debit", "credit", "patient", "payer", "invoice", "shift", "department")


@admin.register(JournalEntry)
class JournalEntryAdmin(ReadOnlyAdmin[JournalEntry]):
    list_display = ("id", "source_type", "source_id", "entry_date", "shift", "posted_at")
    list_filter = ("source_type",)
    search_fields = ("=source_id", "memo")
    date_hierarchy = "entry_date"
    inlines = (JournalLineInline,)


@admin.register(JournalLine)
class JournalLineAdmin(ReadOnlyAdmin[JournalLine]):
    list_display = ("entry", "account", "debit", "credit", "patient", "payer", "invoice", "shift")
    list_filter = ("account",)
