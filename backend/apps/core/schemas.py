from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from typing import Annotated, Any, ClassVar, Literal

from django.utils import timezone
from ninja import Field, Schema

LanguageCode = Literal["ar", "en"]
ThemeCode = Literal["light", "dark", "warm"]
RoleCode = Literal[
    "receptionist",
    "doctor",
    "cashier",
    "cashier_supervisor",
    "pharmacist",
    "lab_tech",
    "lab_supervisor",
    "nurse",
    "accountant",
    "manager",
    "admin",
    "display",
]
ReasonCategoryCode = Literal[
    "line_cancel",
    "visit_cancel",
    "discount",
    "refund",
    "credit_note",
    "stock_adjust",
    "variance",
    "override",
    "writeoff",
    "perform_first",
    "transfer_reject",
    "result_amend",
    "sample_reject",
    "patient_merge",
    "appointment_cancel",
    "admission_cancel",
]
PrintDocumentCode = Literal[
    "invoice", "receipt", "prescription", "lab_result", "claim_export", "shift_report"
]
PaperCode = Literal["a4", "thermal_80"]

#: Department, room and other short reference codes (upper case, start with a letter).
SHORT_CODE = r"^[A-Z][A-Z0-9_-]{0,19}$"
REASON_CODE = r"^[A-Z][A-Z0-9_]{0,39}$"


class PatchSchema(Schema):
    """PATCH body: only the fields sent change; null clears only the ``NULLABLE`` ones."""

    NULLABLE: ClassVar[frozenset[str]] = frozenset()

    def changes(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in self.model_dump(exclude_unset=True).items()
            if value is not None or key in self.NULLABLE
        }


class LoginIn(Schema):
    username: str = Field(..., min_length=1, max_length=150)
    password: str = Field(..., min_length=1, max_length=256)


class MeOut(Schema):
    id: int
    username: str
    full_name_ar: str
    full_name_en: str
    roles: list[str] = Field(..., description="Role codes, sorted")
    permissions: list[str] = Field(
        ..., description="Effective permission codes, sorted. For hiding UI only."
    )
    language: LanguageCode | None = Field(
        ..., description="null = never chosen: the client keeps the device's language"
    )
    theme: ThemeCode | None = Field(
        ..., description="null = never chosen: the client follows prefers-color-scheme"
    )
    must_change_password: bool


class PreferencesPatch(Schema):
    language: LanguageCode | None = None
    theme: ThemeCode | None = None


class ChangePasswordIn(Schema):
    old_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=1, max_length=256)


# --- Administration: users ---------------------------------------------------------------


class UserOut(Schema):
    id: int
    username: str
    full_name_ar: str
    full_name_en: str
    phone: str
    roles: list[str] = Field(..., description="Role codes, sorted")
    is_active: bool
    is_superuser: bool
    must_change_password: bool
    locked: bool = Field(..., description="Login is refused until locked_until")
    locked_until: datetime | None
    failed_login_count: int
    last_login: datetime | None
    date_joined: datetime
    doctor_profile_id: int | None

    @staticmethod
    def resolve_roles(obj: Any) -> list[str]:
        return sorted(r.code for r in obj.roles.all())

    @staticmethod
    def resolve_locked(obj: Any) -> bool:
        return bool(obj.is_locked())

    @staticmethod
    def resolve_locked_until(obj: Any) -> datetime | None:
        until: datetime | None = obj.locked_until
        return until if until is not None and until > timezone.now() else None

    @staticmethod
    def resolve_doctor_profile_id(obj: Any) -> int | None:
        profile = getattr(obj, "doctor_profile", None)
        return profile.pk if profile is not None else None


class UserIn(Schema):
    username: str = Field(..., min_length=1, max_length=150, pattern=r"^[\w.@+-]+$")
    full_name_ar: str = Field("", max_length=150)
    full_name_en: str = Field("", max_length=150)
    phone: str = Field("", max_length=30)
    roles: list[RoleCode] = Field(..., min_length=1, max_length=12)
    password: str = Field(..., min_length=1, max_length=256, description="Temporary password")


class UserPatch(PatchSchema):
    full_name_ar: str | None = Field(None, max_length=150)
    full_name_en: str | None = Field(None, max_length=150)
    phone: str | None = Field(None, max_length=30)
    is_active: bool | None = None
    roles: list[RoleCode] | None = Field(None, min_length=1, max_length=12)


class ResetPasswordIn(Schema):
    new_password: str = Field(..., min_length=1, max_length=256)


class ReasonIn(Schema):
    reason: str = Field(..., min_length=1, max_length=500)


# --- Roles and the permission matrix -----------------------------------------------------


class RoleOut(Schema):
    code: str
    name_ar: str
    name_en: str
    user_count: int = Field(..., description="Active users holding the role")


class PermissionRowOut(Schema):
    code: str
    app: str
    label_ar: str
    label_en: str
    default_roles: list[str]
    granted_roles: list[str] = Field(..., description="Roles that grant the code now")
    overridden_roles: list[str] = Field(..., description="Roles whose cell differs from default")
    protected_roles: list[str] = Field(..., description="Roles that can never lose the code")


class MatrixChangeOut(Schema):
    role: str
    code: str
    allowed: bool


class PermissionMatrixOut(Schema):
    roles: list[RoleOut]
    permissions: list[PermissionRowOut]
    changed: list[MatrixChangeOut] = Field(
        default_factory=list, description="Cells whose grant flipped (on update only)"
    )


class MatrixChangeIn(Schema):
    role: RoleCode
    code: str = Field(..., min_length=3, max_length=100)
    allowed: bool


class PermissionMatrixIn(Schema):
    changes: list[MatrixChangeIn] = Field(..., min_length=1, max_length=1000)
    reason: str = Field(..., min_length=1, max_length=500)


# --- Center profile, policy ---------------------------------------------------------------


class CenterProfileOut(Schema):
    name_ar: str
    name_en: str
    address: str
    phone: str
    registration_no: str
    tax_no: str
    digits: Literal["latin", "arabic"]
    has_logo: bool
    logo_url: str | None = Field(..., description="Changes whenever the logo changes")
    updated_at: datetime | None

    @staticmethod
    def resolve_has_logo(obj: Any) -> bool:
        return bool(obj.logo.name)

    @staticmethod
    def resolve_logo_url(obj: Any) -> str | None:
        if not obj.logo.name:
            return None
        version = obj.updated_at.strftime("%Y%m%d%H%M%S%f") if obj.updated_at else "0"
        return f"/api/core/center/logo?v={version}"


class CenterProfileIn(Schema):
    name_ar: str = Field(..., max_length=200)
    name_en: str = Field(..., max_length=200)
    address: str = Field("", max_length=300)
    phone: str = Field("", max_length=50)
    registration_no: str = Field("", max_length=100)
    tax_no: str = Field("", max_length=100)
    digits: Literal["latin", "arabic"] = "latin"


Percent = Annotated[int, Field(ge=0, le=100)]


class PolicyOut(Schema):
    allow_partial_payment: bool
    default_pay_first: bool = Field(..., description="Always true (invariant 1); read-only")
    pending_transfer_alert_days: int
    partial_dispense_remainder: Literal["defer", "refund"]
    show_estimated_cost: bool
    follow_up_window_days: int
    follow_up_discount_percent: Decimal
    discount_limit_percent: dict[str, float]
    session_idle_minutes: int
    perform_first_roles: list[str]
    updated_at: datetime | None


class PolicyIn(Schema):
    allow_partial_payment: bool
    pending_transfer_alert_days: int = Field(..., ge=1, le=90)
    partial_dispense_remainder: Literal["defer", "refund"]
    show_estimated_cost: bool
    follow_up_window_days: int = Field(..., ge=0, le=365)
    follow_up_discount_percent: Decimal = Field(..., ge=0, le=100, decimal_places=2)
    discount_limit_percent: dict[RoleCode, Percent]
    session_idle_minutes: int = Field(..., ge=5, le=1440)
    perform_first_roles: list[RoleCode] = Field(..., max_length=12)


# --- Departments, rooms, doctors ---------------------------------------------------------


class DepartmentOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str
    active: bool
    sort_order: int
    room_count: int = 0
    doctor_count: int = Field(0, description="Active doctors")


class DepartmentIn(Schema):
    code: str = Field(..., pattern=SHORT_CODE)
    name_ar: str = Field(..., min_length=1, max_length=150)
    name_en: str = Field(..., min_length=1, max_length=150)
    active: bool = True
    sort_order: int = Field(0, ge=0, le=32767)


class DepartmentPatch(PatchSchema):
    name_ar: str | None = Field(None, min_length=1, max_length=150)
    name_en: str | None = Field(None, min_length=1, max_length=150)
    active: bool | None = None
    sort_order: int | None = Field(None, ge=0, le=32767)


class RoomOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str
    active: bool
    department_id: int | None
    department_code: str | None

    @staticmethod
    def resolve_department_code(obj: Any) -> str | None:
        return obj.department.code if obj.department_id else None


class RoomIn(Schema):
    code: str = Field(..., pattern=SHORT_CODE)
    name_ar: str = Field(..., min_length=1, max_length=150)
    name_en: str = Field(..., min_length=1, max_length=150)
    department_id: int | None = None
    active: bool = True


class RoomPatch(PatchSchema):
    NULLABLE: ClassVar[frozenset[str]] = frozenset({"department_id"})

    name_ar: str | None = Field(None, min_length=1, max_length=150)
    name_en: str | None = Field(None, min_length=1, max_length=150)
    department_id: int | None = None
    active: bool | None = None


class ScheduleSessionOut(Schema):
    id: int
    weekday: int = Field(..., description="0 = Monday ... 6 = Sunday")
    start_time: time
    end_time: time
    slot_minutes: int
    room_id: int | None
    room_code: str | None

    @staticmethod
    def resolve_room_code(obj: Any) -> str | None:
        return obj.room.code if obj.room_id else None


class DoctorOut(Schema):
    id: int
    user_id: int
    username: str
    full_name_ar: str
    full_name_en: str
    department_id: int
    department_code: str
    specialty_ar: str
    specialty_en: str
    consultation_service_id: int | None
    consultation_service_code: str | None
    active: bool
    schedule: list[ScheduleSessionOut]

    @staticmethod
    def resolve_username(obj: Any) -> str:
        return str(obj.user.username)

    @staticmethod
    def resolve_full_name_ar(obj: Any) -> str:
        return str(obj.user.full_name_ar)

    @staticmethod
    def resolve_full_name_en(obj: Any) -> str:
        return str(obj.user.full_name_en)

    @staticmethod
    def resolve_department_code(obj: Any) -> str:
        return str(obj.department.code)

    @staticmethod
    def resolve_consultation_service_code(obj: Any) -> str | None:
        return obj.consultation_service.code if obj.consultation_service_id else None

    @staticmethod
    def resolve_schedule(obj: Any) -> list[Any]:
        return list(obj.schedules.all())


class DoctorCandidateOut(Schema):
    """A user who can be given a doctor profile: names only, no account details."""

    id: int
    username: str
    full_name_ar: str
    full_name_en: str


class DoctorIn(Schema):
    user_id: int
    department_id: int
    specialty_ar: str = Field("", max_length=150)
    specialty_en: str = Field("", max_length=150)
    consultation_service_id: int | None = None
    active: bool = True


class DoctorPatch(PatchSchema):
    NULLABLE: ClassVar[frozenset[str]] = frozenset({"consultation_service_id"})

    department_id: int | None = None
    specialty_ar: str | None = Field(None, max_length=150)
    specialty_en: str | None = Field(None, max_length=150)
    consultation_service_id: int | None = None
    active: bool | None = None


class ScheduleSessionIn(Schema):
    weekday: int = Field(..., ge=0, le=6, description="0 = Monday ... 6 = Sunday")
    start_time: time
    end_time: time
    slot_minutes: int = Field(15, ge=1, le=1440)
    room_id: int | None = None


class ScheduleIn(Schema):
    sessions: list[ScheduleSessionIn] = Field(..., max_length=100)


# --- Reason codes, numbering, print templates ---------------------------------------------


class ReasonCodeOut(Schema):
    id: int
    category: str
    code: str
    label_ar: str
    label_en: str
    requires_note: bool
    active: bool
    sort_order: int


class ReasonCodeIn(Schema):
    category: ReasonCategoryCode
    code: str = Field(..., pattern=REASON_CODE)
    label_ar: str = Field(..., min_length=1, max_length=200)
    label_en: str = Field(..., min_length=1, max_length=200)
    requires_note: bool = False
    sort_order: int = Field(0, ge=0, le=32767)


class ReasonCodePatch(PatchSchema):
    label_ar: str | None = Field(None, min_length=1, max_length=200)
    label_en: str | None = Field(None, min_length=1, max_length=200)
    requires_note: bool | None = None
    active: bool | None = None
    sort_order: int | None = Field(None, ge=0, le=32767)


class SequenceOut(Schema):
    code: str
    last_value: int
    last_number: str | None
    next_number: str


class SequencesOut(Schema):
    year: int
    years: list[int]
    items: list[SequenceOut]


class PrintTemplateOut(Schema):
    document: PrintDocumentCode
    paper: PaperCode
    show_logo: bool
    header_ar: str
    header_en: str
    footer_ar: str
    footer_en: str
    active: bool
    saved: bool = Field(..., description="False: defaults, never saved")
    updated_at: datetime | None


class PrintTemplateIn(Schema):
    show_logo: bool = True
    header_ar: str = Field("", max_length=1000)
    header_en: str = Field("", max_length=1000)
    footer_ar: str = Field("", max_length=1000)
    footer_en: str = Field("", max_length=1000)
    active: bool = True


# --- List filters -------------------------------------------------------------------------


class UserListParams(Schema):
    page: int = Field(1, ge=1)
    page_size: int = Field(25, ge=1, le=100)
    q: str | None = Field(None, max_length=200)
    role: RoleCode | None = None
    active: bool | None = None


class DepartmentListParams(Schema):
    active: bool | None = None


class RoomListParams(Schema):
    department_id: int | None = None
    active: bool | None = None


class DoctorListParams(Schema):
    department_id: int | None = None
    active: bool | None = None


class ReasonCodeListParams(Schema):
    category: ReasonCategoryCode | None = None
    active: bool | None = None


class SequenceParams(Schema):
    year: int | None = Field(None, ge=2000, le=2999)
