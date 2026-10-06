from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.http import HttpRequest

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


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    inlines = (UserRoleInline,)
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
    readonly_fields = ("last_login", "date_joined", "failed_login_count")
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
