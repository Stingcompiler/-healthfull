"""Core models: users, roles and the permission matrix, center settings, numbering,
reason codes, departments, rooms, doctor profiles, notifications and the login audit.

Every mutable configuration model is tracked by django-pghistory (insert, update, delete
snapshots linked to the request context set by ``api.middleware``).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar, Self

import pghistory
import pgtrigger
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.roles import ROLE_CODES
from domain.errors import DomainError
from domain.lockout import LockState, is_locked
from domain.throttle import WindowState


def _full_history() -> list[pghistory.RowEvent]:
    return [pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent()]


class Language(models.TextChoices):
    AR = "ar", "العربية"
    EN = "en", "English"


class Theme(models.TextChoices):
    LIGHT = "light", "Light"
    DARK = "dark", "Dark"
    WARM = "warm", "Warm"


class DigitStyle(models.TextChoices):
    LATIN = "latin", "Latin (0123)"
    ARABIC = "arabic", "Arabic-Indic (٠١٢٣)"


# --- Roles and users --------------------------------------------------------------------


@pghistory.track(*_full_history())
class Role(models.Model):
    code = models.CharField(max_length=40, unique=True)
    name_ar = models.CharField(max_length=100)
    name_en = models.CharField(max_length=100)

    class Meta:
        ordering: ClassVar[list[str]] = ["code"]

    def __str__(self) -> str:
        return self.name_en or self.code

    def clean(self) -> None:
        if self.code not in ROLE_CODES:
            raise ValidationError({"code": f"Unknown role code {self.code!r}"})


@pghistory.track(
    pghistory.InsertEvent(),
    pghistory.UpdateEvent(),
    exclude=["password", "last_login", "failed_login_count", "locked_until"],
)
class User(AbstractUser):
    full_name_ar = models.CharField(max_length=150, blank=True)
    full_name_en = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    # "" = the user never chose (MeOut sends null): the client keeps the device's choice
    # (pre-login pick, then prefers-color-scheme) and saves it at first login (ARCHITECTURE 5.1).
    language = models.CharField(max_length=2, choices=Language.choices, blank=True, default="")
    theme = models.CharField(max_length=10, choices=Theme.choices, blank=True, default="")
    must_change_password = models.BooleanField(
        default=True, help_text="Forces a password change at next login (FEATURES 0.1)."
    )
    failed_login_count = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    # Audited proxy for password changes: the hash itself is never copied into history.
    password_changed_at = models.DateTimeField(null=True, blank=True, editable=False)
    roles: models.ManyToManyField[Role, UserRole] = models.ManyToManyField(
        Role, through="UserRole", related_name="users", blank=True
    )

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"
        ordering: ClassVar[list[str]] = ["username"]

    def __str__(self) -> str:
        return self.username

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self._state.adding and self.password_changed_at is None and self.password:
            self.password_changed_at = timezone.now()
        super().save(*args, **kwargs)

    def set_password(self, raw_password: str | None) -> None:
        super().set_password(raw_password)
        self.password_changed_at = timezone.now()

    @property
    def display_name_ar(self) -> str:
        return self.full_name_ar or self.full_name_en or self.username

    @property
    def display_name_en(self) -> str:
        return self.full_name_en or self.full_name_ar or self.username

    @property
    def lock_state(self) -> LockState:
        return LockState(failed_count=self.failed_login_count, locked_until=self.locked_until)

    def is_locked(self, now: datetime | None = None) -> bool:
        return is_locked(self.lock_state, now or timezone.now())

    def role_codes(self) -> list[str]:
        return sorted(self.roles.values_list("code", flat=True))


@pghistory.track(pghistory.InsertEvent(), pghistory.DeleteEvent())
class UserRole(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="role_users")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["user", "role"], name="core_userrole_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.role_id}"


@pghistory.track(*_full_history())
class RolePermission(models.Model):
    """Override of a permission code's default for one role (the editable matrix)."""

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permission_overrides")
    code = models.CharField(max_length=100)
    allowed = models.BooleanField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["role__code", "code"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["role", "code"], name="core_rolepermission_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.role_id}:{self.code}={'allow' if self.allowed else 'deny'}"

    def clean(self) -> None:
        from apps.core.permissions import is_registered

        if not is_registered(self.code):
            raise ValidationError({"code": f"Unknown permission code {self.code!r}"})


# --- Singletons ------------------------------------------------------------------------


class SingletonModel(models.Model):
    """A table that always holds exactly one row with primary key 1."""

    SINGLETON_PK: ClassVar[int] = 1

    class Meta:
        abstract = True
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(condition=models.Q(id=1), name="%(app_label)s_%(class)s_single"),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.pk = self.SINGLETON_PK
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise DomainError("SINGLETON_NOT_DELETABLE", f"{type(self).__name__} cannot be deleted")

    @classmethod
    def load(cls) -> Self:
        obj, _ = cls._default_manager.get_or_create(pk=cls.SINGLETON_PK)
        return obj


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent())
class CenterProfile(SingletonModel):
    """Identity of the medical center, printed on documents (FEATURES 13.1)."""

    name_ar = models.CharField(max_length=200, blank=True)
    name_en = models.CharField(max_length=200, blank=True)
    address = models.CharField(max_length=300, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    logo = models.FileField(upload_to="center/", blank=True)
    registration_no = models.CharField(max_length=100, blank=True)
    tax_no = models.CharField(max_length=100, blank=True)
    digits = models.CharField(max_length=10, choices=DigitStyle.choices, default=DigitStyle.LATIN)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(SingletonModel.Meta):
        verbose_name = "center profile"

    def __str__(self) -> str:
        return self.name_en or self.name_ar or "Center profile"


class PrintDocument(models.TextChoices):
    INVOICE = "invoice", "Invoice"
    RECEIPT = "receipt", "Receipt"
    PRESCRIPTION = "prescription", "Prescription"
    LAB_RESULT = "lab_result", "Lab result"
    CLAIM_EXPORT = "claim_export", "Claim export"
    SHIFT_REPORT = "shift_report", "Shift report"


class PaperSize(models.TextChoices):
    A4 = "a4", "A4"
    THERMAL_80 = "thermal_80", "Thermal 80 mm"


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class PrintTemplate(models.Model):
    """Header and footer of one printed document on one paper size (FEATURES 0.10, 13.7)."""

    document = models.CharField(max_length=20, choices=PrintDocument.choices)
    paper = models.CharField(max_length=20, choices=PaperSize.choices, default=PaperSize.A4)
    show_logo = models.BooleanField(default=True)
    header_ar = models.TextField(blank=True)
    header_en = models.TextField(blank=True)
    footer_ar = models.TextField(blank=True)
    footer_en = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "print template"
        ordering: ClassVar[list[str]] = ["document", "paper"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["document", "paper"], name="core_printtemplate_one_per_paper"
            ),
            models.CheckConstraint(
                condition=models.Q(document__in=PrintDocument.values),
                name="core_printtemplate_document_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(paper__in=PaperSize.values),
                name="core_printtemplate_paper_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.document} ({self.paper})"


def _default_discount_limits() -> dict[str, int]:
    return {"cashier": 0, "cashier_supervisor": 25, "accountant": 25, "manager": 100}


def _default_perform_first_roles() -> list[str]:
    return ["cashier_supervisor", "manager"]


class PartialDispenseRemainder(models.TextChoices):
    """What happens to the undispensed rest of a partly dispensed line (FLOW 6, FEATURES 8.3)."""

    DEFER = "defer", "Keep it open to dispense later"
    REFUND = "refund", "Cancel it and refund the patient"


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent())
class Policy(SingletonModel):
    """Center-wide policy switches (FEATURES 13.4).

    ``default_pay_first`` is documentation, not a switch: pay-first is invariant 1, and
    perform-first exists only as a documented authorization (ADR 0006). The database keeps it
    on.
    """

    allow_partial_payment = models.BooleanField(default=False)
    default_pay_first = models.BooleanField(
        default=True, help_text="Always on: perform-first needs an authorization (invariant 1)."
    )
    pending_transfer_alert_days = models.PositiveSmallIntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(90)],
        help_text="Alert verifiers about transfers pending longer than this (FEATURES 0.13).",
    )
    partial_dispense_remainder = models.CharField(
        max_length=10,
        choices=PartialDispenseRemainder.choices,
        default=PartialDispenseRemainder.DEFER,
        help_text="Default for the undispensed rest of a line when stock runs short (FLOW 6).",
    )
    show_estimated_cost = models.BooleanField(
        default=False,
        help_text="Doctors with the permission may see an estimated cost of orders (3.8).",
    )
    follow_up_window_days = models.PositiveSmallIntegerField(default=7)
    follow_up_discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("100.00"),
        validators=[MinValueValidator(Decimal(0)), MaxValueValidator(Decimal(100))],
    )
    discount_limit_percent = models.JSONField(
        default=_default_discount_limits,
        help_text='Maximum discount percent per role code, e.g. {"cashier": 0}.',
    )
    session_idle_minutes = models.PositiveIntegerField(
        default=480, validators=[MinValueValidator(5), MaxValueValidator(24 * 60)]
    )
    perform_first_roles = models.JSONField(
        default=_default_perform_first_roles,
        help_text="Role codes allowed to authorize perform-first exceptions.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(SingletonModel.Meta):
        verbose_name = "policy"
        verbose_name_plural = "policy"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            *SingletonModel.Meta.constraints,
            models.CheckConstraint(
                condition=models.Q(follow_up_discount_percent__gte=0)
                & models.Q(follow_up_discount_percent__lte=100),
                name="core_policy_follow_up_discount_range",
            ),
            models.CheckConstraint(
                condition=models.Q(session_idle_minutes__gte=5)
                & models.Q(session_idle_minutes__lte=1440),
                name="core_policy_session_idle_range",
            ),
            models.CheckConstraint(
                condition=models.Q(default_pay_first=True), name="core_policy_pay_first_always"
            ),
            models.CheckConstraint(
                condition=models.Q(pending_transfer_alert_days__gte=1)
                & models.Q(pending_transfer_alert_days__lte=90),
                name="core_policy_transfer_alert_range",
            ),
            models.CheckConstraint(
                condition=models.Q(partial_dispense_remainder__in=PartialDispenseRemainder.values),
                name="core_policy_partial_dispense_valid",
            ),
        ]

    def __str__(self) -> str:
        return "Policy"

    def clean(self) -> None:
        errors: dict[str, str] = {}
        limits = self.discount_limit_percent
        if not isinstance(limits, dict):
            errors["discount_limit_percent"] = "Must be an object of role code -> percent."
        else:
            for role, pct in limits.items():
                if role not in ROLE_CODES:
                    errors["discount_limit_percent"] = f"Unknown role code {role!r}."
                elif (
                    isinstance(pct, bool)
                    or not isinstance(pct, int | float)
                    or not (0 <= pct <= 100)
                ):
                    errors["discount_limit_percent"] = f"Percent for {role!r} must be 0-100."
        roles_ = self.perform_first_roles
        if not isinstance(roles_, list) or not all(r in ROLE_CODES for r in roles_):
            errors["perform_first_roles"] = "Must be a list of known role codes."
        if errors:
            raise ValidationError(errors)

    def discount_limit_for(self, role_codes: list[str]) -> Decimal:
        """Highest discount percent allowed to a holder of ``role_codes``."""
        limits = (
            self.discount_limit_percent if isinstance(self.discount_limit_percent, dict) else {}
        )
        values = [Decimal(str(limits[r])) for r in role_codes if r in limits]
        return max(values, default=Decimal(0))


# --- Numbering -------------------------------------------------------------------------


class Sequence(models.Model):
    """Per-prefix, per-year document counter. Use ``apps.core.services.next_number``."""

    code = models.CharField(max_length=10)
    year = models.PositiveSmallIntegerField()
    last_value = models.PositiveBigIntegerField(default=0)

    class Meta:
        ordering: ClassVar[list[str]] = ["code", "-year"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["code", "year"], name="core_sequence_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.code}-{self.year}: {self.last_value}"


# --- Reference data --------------------------------------------------------------------


class ReasonCategory(models.TextChoices):
    """What a reason code explains. Seeded by migrations ``0007_seed_reason_codes`` and ``0009``."""

    LINE_CANCEL = "line_cancel", "Service line cancellation"
    VISIT_CANCEL = "visit_cancel", "Visit cancellation"
    DISCOUNT = "discount", "Discount or exemption"
    REFUND = "refund", "Refund"
    CREDIT_NOTE = "credit_note", "Credit note"
    STOCK_ADJUST = "stock_adjust", "Stock adjustment"
    VARIANCE = "variance", "Shift cash variance"
    OVERRIDE = "override", "Supervisor override"
    WRITEOFF = "writeoff", "Payer rejection: rebill or write off"
    PERFORM_FIRST = "perform_first", "Perform-first authorization"
    TRANSFER_REJECT = "transfer_reject", "Bank transfer rejection"
    RESULT_AMEND = "result_amend", "Lab result amendment"
    SAMPLE_REJECT = "sample_reject", "Lab sample rejection"
    PATIENT_MERGE = "patient_merge", "Patient file merge"
    APPOINTMENT_CANCEL = "appointment_cancel", "Appointment cancellation"


@pghistory.track(*_full_history())
class ReasonCode(models.Model):
    """Configurable reasons for cancellations, discounts, refunds, overrides (FEATURES 13.5).

    Invariant 4: every cancellation, discount, refund, transfer confirmation/rejection and
    override stores a ``ReasonCode`` of the matching category plus free text.
    """

    category = models.CharField(max_length=40, choices=ReasonCategory.choices, db_index=True)
    code = models.CharField(max_length=40)
    label_ar = models.CharField(max_length=200)
    label_en = models.CharField(max_length=200)
    requires_note = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering: ClassVar[list[str]] = ["category", "sort_order", "code"]
        verbose_name = "reason code"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["category", "code"], name="core_reasoncode_unique"),
            models.CheckConstraint(
                condition=models.Q(category__in=ReasonCategory.values),
                name="core_reasoncode_category_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.category}/{self.code}"


@pghistory.track(*_full_history())
class Department(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name_ar = models.CharField(max_length=150)
    name_en = models.CharField(max_length=150)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering: ClassVar[list[str]] = ["sort_order", "code"]

    def __str__(self) -> str:
        return self.name_en or self.code


@pghistory.track(*_full_history())
class Room(models.Model):
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="rooms", null=True, blank=True
    )
    code = models.CharField(max_length=20, unique=True)
    name_ar = models.CharField(max_length=150)
    name_en = models.CharField(max_length=150)
    active = models.BooleanField(default=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["code"]

    def __str__(self) -> str:
        return self.name_en or self.code


@pghistory.track(*_full_history())
class DoctorProfile(models.Model):
    """Clinical profile of a user who sees patients.

    ``consultation_service`` is the catalog service billed as the consultation fee line that
    a new visit with this doctor creates automatically (FEATURES 2.2).
    """

    user = models.OneToOneField(User, on_delete=models.PROTECT, related_name="doctor_profile")
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="doctors")
    specialty_ar = models.CharField(max_length=150, blank=True)
    specialty_en = models.CharField(max_length=150, blank=True)
    consultation_service = models.ForeignKey(
        "catalog.Service",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="consultation_doctors",
        help_text="Consultation fee service (kind 'consultation') for visits with this doctor.",
    )
    active = models.BooleanField(default=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["user__username"]

    def __str__(self) -> str:
        return f"Dr. {self.user.display_name_en}"


# --- Notifications and login audit --------------------------------------------------------


class Notification(models.Model):
    """In-app notification for one user (FEATURES 0.13)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=60)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "read_at"], name="core_notif_user_read_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} -> {self.user_id}"


class AuthEventKind(models.TextChoices):
    LOGIN_SUCCESS = "login_success", "Login succeeded"
    LOGIN_FAILED = "login_failed", "Login failed"
    LOGIN_LOCKED = "login_locked", "Login refused: account locked"
    ACCOUNT_LOCKED = "account_locked", "Account locked after repeated failures"
    LOGOUT = "logout", "Logout"
    PASSWORD_CHANGED = "password_changed", "Password changed"
    PASSWORD_CHANGE_FAILED = "password_change_failed", "Password change rejected"
    LOGIN_THROTTLED = "login_throttled", "Login refused: too many failures from this address"
    ACCOUNT_UNLOCKED = "account_unlocked", "Account unlocked by an administrator"
    PASSWORD_RESET = "password_reset", "Password reset by an administrator"


class AuthEvent(models.Model):
    """Append-only session and login audit (FEATURES 14.4). Protected by a DB trigger."""

    kind = models.CharField(max_length=30, choices=AuthEventKind.choices)
    # PROTECT: audited users are deactivated, never deleted (rows here are immutable).
    user = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name="auth_events"
    )
    username = models.CharField(max_length=150, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            pgtrigger.Protect(
                name="append_only",
                operation=pgtrigger.Update | pgtrigger.Delete,
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.username} @ {self.created_at:%Y-%m-%d %H:%M}"


class ThrottleScope(models.TextChoices):
    IP = "ip", "Failed logins per client address"
    USERNAME = "username", "Failed logins for a username that does not exist"


class LoginThrottle(models.Model):
    """Login abuse counters that are not stored on a ``User`` row (FEATURES 14.4).

    * ``scope=ip``: failed logins per client address in a fixed window
      (``domain.throttle``); over the limit, logins from that address get 429.
    * ``scope=username``: the lockout state (``domain.lockout``) of a username that has no
      account, so unknown and existing usernames lock the same way and the 423 response
      cannot be used to find out which usernames exist.

    Rows are bookkeeping, not audit (that is ``AuthEvent``); expired rows are removed by
    ``manage.py maintenance``.
    """

    scope = models.CharField(max_length=10, choices=ThrottleScope.choices)
    key = models.CharField(max_length=150)
    count = models.PositiveIntegerField(default=0)
    window_started_at = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["scope", "key"], name="core_loginthrottle_unique"),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["updated_at"], name="core_throttle_updated_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.scope}:{self.key}={self.count}"

    @property
    def window_state(self) -> WindowState:
        return WindowState(count=self.count, window_started_at=self.window_started_at)

    @property
    def lock_state(self) -> LockState:
        return LockState(failed_count=self.count, locked_until=self.locked_until)
