from __future__ import annotations

from typing import Any

from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.template.response import TemplateResponse

from apps.core.models import (
    AuthEvent,
    CenterProfile,
    Department,
    DoctorProfile,
    Notification,
    Policy,
    ReasonCode,
    Role,
    RolePermission,
    Room,
    Sequence,
    User,
    UserRole,
)


class UserRoleInline(admin.TabularInline[UserRole, User]):
    model = UserRole
    extra = 0
    autocomplete_fields = ("role",)
    readonly_fields = ("created_at",)


class UnlockReasonForm(forms.Form):
    reason = forms.CharField(
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Why these accounts are being unlocked (kept in the login audit).",
    )


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    inlines = (UserRoleInline,)
    actions = ("unlock_accounts",)
    list_display = (
        "username",
        "full_name_ar",
        "full_name_en",
        "is_active",
        "is_staff",
        "must_change_password",
        "locked_until",
        "last_login",
    )
    list_filter = ("is_active", "is_staff", "is_superuser", "user_roles__role", "language")
    search_fields = ("username", "full_name_ar", "full_name_en", "phone", "email")
    # Lock fields change only through login bookkeeping or the audited unlock action.
    readonly_fields = ("last_login", "date_joined", "failed_login_count", "locked_until")
    fieldsets = (
        *(DjangoUserAdmin.fieldsets or ()),
        (
            "Hospital profile",
            {
                "fields": (
                    "full_name_ar",
                    "full_name_en",
                    "phone",
                    "language",
                    "theme",
                    "must_change_password",
                    "failed_login_count",
                    "locked_until",
                )
            },
        ),
    )
    add_fieldsets = (
        *(DjangoUserAdmin.add_fieldsets or ()),
        ("Hospital profile", {"fields": ("full_name_ar", "full_name_en", "phone")}),
    )

    @admin.action(
        description="Unlock selected accounts (asks for a reason)", permissions=("change",)
    )
    def unlock_accounts(
        self, request: HttpRequest, queryset: QuerySet[User]
    ) -> TemplateResponse | None:
        from apps.core import services

        form = UnlockReasonForm(request.POST if "apply" in request.POST else None)
        if form.is_valid():
            count = services.unlock_accounts(
                request, list(queryset), reason=form.cleaned_data["reason"]
            )
            self.message_user(request, f"Unlocked {count} account(s).", messages.SUCCESS)
            return None
        return TemplateResponse(
            request,
            "admin/core/user/unlock_accounts.html",
            {
                **self.admin_site.each_context(request),
                "title": "Unlock accounts",
                "opts": self.model._meta,
                "form": form,
                "users": queryset,
                "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
            },
        )


class RolePermissionInline(admin.TabularInline[RolePermission, Role]):
    model = RolePermission
    extra = 0


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin[Role]):
    list_display = ("code", "name_ar", "name_en")
    search_fields = ("code", "name_ar", "name_en")
    readonly_fields = ("code",)
    inlines = (RolePermissionInline,)

    # The role set is fixed (ARCHITECTURE 4.10); only names and the matrix are editable.
    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


class SingletonAdmin[M: CenterProfile | Policy](admin.ModelAdmin[M]):
    def has_add_permission(self, request: HttpRequest) -> bool:
        return not self.model._default_manager.exists()

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(CenterProfile)
class CenterProfileAdmin(SingletonAdmin[CenterProfile]):
    list_display = ("name_ar", "name_en", "phone", "digits", "updated_at")


@admin.register(Policy)
class PolicyAdmin(SingletonAdmin[Policy]):
    list_display = (
        "allow_partial_payment",
        "default_pay_first",
        "follow_up_window_days",
        "follow_up_discount_percent",
        "session_idle_minutes",
        "updated_at",
    )


@admin.register(Sequence)
class SequenceAdmin(admin.ModelAdmin[Sequence]):
    list_display = ("code", "year", "last_value")
    list_filter = ("code", "year")
    # Counters move only through apps.core.services.next_number.
    readonly_fields = ("code", "year", "last_value")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(ReasonCode)
class ReasonCodeAdmin(admin.ModelAdmin[ReasonCode]):
    list_display = ("category", "code", "label_ar", "label_en", "requires_note", "active")
    list_filter = ("category", "active")
    search_fields = ("code", "label_ar", "label_en")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin[Department]):
    list_display = ("code", "name_ar", "name_en", "active", "sort_order")
    list_filter = ("active",)
    search_fields = ("code", "name_ar", "name_en")


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin[Room]):
    list_display = ("code", "name_ar", "name_en", "department", "active")
    list_filter = ("active", "department")
    search_fields = ("code", "name_ar", "name_en")


@admin.register(DoctorProfile)
class DoctorProfileAdmin(admin.ModelAdmin[DoctorProfile]):
    list_display = ("user", "department", "specialty_ar", "specialty_en", "active")
    list_filter = ("active", "department")
    search_fields = ("user__username", "user__full_name_ar", "user__full_name_en")
    autocomplete_fields = ("user",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin[Notification]):
    list_display = ("user", "kind", "created_at", "read_at")
    list_filter = ("kind",)
    search_fields = ("user__username", "kind")
    raw_id_fields = ("user",)


@admin.register(AuthEvent)
class AuthEventAdmin(admin.ModelAdmin[AuthEvent]):
    """Read-only: rows are append-only (DB trigger)."""

    list_display = ("created_at", "kind", "username", "ip_address", "request_id")
    list_filter = ("kind",)
    search_fields = ("username", "ip_address", "request_id")
    date_hierarchy = "created_at"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
