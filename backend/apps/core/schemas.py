from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Any, ClassVar, Literal

from django.utils import timezone
from ninja import Field, Schema

from domain.center_page import announcement_visible

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
    "invoice", "receipt", "prescription", "referral", "lab_result", "claim_export", "shift_report"
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


HHMM = Annotated[str, Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$", examples=["08:00"])]


class CenterDayHours(Schema):
    weekday: int = Field(..., ge=0, le=6, description="0 = Monday ... 6 = Sunday")
    closed: bool
    opens: HHMM | None = None
    closes: HHMM | None = None


class CenterFacilityRow(Schema):
    """One facility of the center (at most 20)."""

    name_ar: str = Field("", max_length=80)
    name_en: str = Field("", max_length=80)


class CenterReasonRow(Schema):
    """One reason to choose the center (at most 8)."""

    title_ar: str = Field("", max_length=80)
    title_en: str = Field("", max_length=80)
    text_ar: str = Field("", max_length=200)
    text_en: str = Field("", max_length=200)


class CenterPageOut(Schema):
    about_ar: str
    about_en: str
    hours: list[CenterDayHours] = Field(..., description="Seven days, or empty: not published")
    whatsapp: str = Field(..., description="International digits for a wa.me link")
    email: str
    directions_ar: str
    directions_en: str
    show_about: bool
    show_hours: bool
    show_departments: bool
    show_doctors: bool
    show_announcements: bool
    show_contact: bool
    show_address: bool
    hidden_department_ids: list[int]
    hidden_doctor_ids: list[int]
    hero_title_ar: str
    hero_title_en: str
    hero_text_ar: str
    hero_text_en: str
    facilities: list[CenterFacilityRow]
    reasons: list[CenterReasonRow]
    accessibility_ar: str
    accessibility_en: str
    privacy_ar: str
    privacy_en: str
    cancellation_policy_ar: str
    cancellation_policy_en: str
    maps_url: str = Field(..., description="A plain https link opened by the visitor's phone")
    show_services: bool
    show_insurance: bool
    show_faq: bool
    show_testimonials: bool
    show_facilities: bool
    show_policies: bool
    updated_at: datetime | None


class CenterPageIn(Schema):
    about_ar: str = Field("", max_length=600)
    about_en: str = Field("", max_length=600)
    hours: list[CenterDayHours] = Field(default_factory=list, max_length=7)
    whatsapp: str = Field("", max_length=30)
    email: str = Field("", max_length=120)
    directions_ar: str = Field("", max_length=400)
    directions_en: str = Field("", max_length=400)
    show_about: bool = True
    show_hours: bool = True
    show_departments: bool = True
    show_doctors: bool = True
    show_announcements: bool = True
    show_contact: bool = True
    show_address: bool = True
    hidden_department_ids: list[int] = Field(default_factory=list, max_length=500)
    hidden_doctor_ids: list[int] = Field(default_factory=list, max_length=500)
    hero_title_ar: str = Field("", max_length=120)
    hero_title_en: str = Field("", max_length=120)
    hero_text_ar: str = Field("", max_length=300)
    hero_text_en: str = Field("", max_length=300)
    facilities: list[CenterFacilityRow] = Field(default_factory=list, max_length=20)
    reasons: list[CenterReasonRow] = Field(default_factory=list, max_length=8)
    accessibility_ar: str = Field("", max_length=600)
    accessibility_en: str = Field("", max_length=600)
    privacy_ar: str = Field("", max_length=2000)
    privacy_en: str = Field("", max_length=2000)
    cancellation_policy_ar: str = Field("", max_length=1000)
    cancellation_policy_en: str = Field("", max_length=1000)
    maps_url: str = Field("", max_length=500)
    show_services: bool = True
    show_insurance: bool = True
    show_faq: bool = True
    show_testimonials: bool = True
    show_facilities: bool = True
    show_policies: bool = True


class PublicSiteSettingsOut(Schema):
    """The public site switches and online booking rules (ADR 0028, 0029)."""

    site_enabled: bool = Field(..., description="The center website at / and /portal")
    online_booking_enabled: bool = Field(..., description="Doctor, day and slot reads; booking")
    patient_tracking_enabled: bool = Field(..., description="Patient sign-in and patient pages")
    lead_minutes: int
    horizon_days: int
    max_open: int
    cancel_cutoff_hours: int
    reschedule_allowed: bool
    reschedule_cutoff_hours: int
    require_approval: bool
    request_ttl_hours: int
    guest_booking_enabled: bool
    max_guest_bookings_per_phone: int
    max_pending_per_doctor_day: int
    max_requests_per_address_day: int
    pow_difficulty_bits: int
    guest_retention_days: int
    min_review_minutes: int
    updated_at: datetime | None


class PublicSiteSettingsIn(Schema):
    """A change of the public site settings: omitted or null fields keep their value; the
    reason is required and kept in the history. Ranges: 422 with the field."""

    reason: str = Field(..., max_length=300)
    site_enabled: bool | None = None
    online_booking_enabled: bool | None = None
    patient_tracking_enabled: bool | None = None
    lead_minutes: int | None = None
    horizon_days: int | None = None
    max_open: int | None = None
    cancel_cutoff_hours: int | None = None
    reschedule_allowed: bool | None = None
    reschedule_cutoff_hours: int | None = None
    require_approval: bool | None = None
    request_ttl_hours: int | None = None
    guest_booking_enabled: bool | None = None
    max_guest_bookings_per_phone: int | None = None
    max_pending_per_doctor_day: int | None = None
    max_requests_per_address_day: int | None = None
    pow_difficulty_bits: int | None = None
    guest_retention_days: int | None = None
    min_review_minutes: int | None = None

    def changes(self) -> dict[str, Any]:
        return {k: v for k, v in self.dict().items() if v is not None and k != "reason"}


class AnnouncementOut(Schema):
    id: int
    title_ar: str
    title_en: str
    body_ar: str
    body_en: str
    starts_on: date | None
    ends_on: date | None
    active: bool
    sort_order: int
    shown_today: bool = Field(..., description="Public on the center page today")
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_shown_today(obj: Any) -> bool:
        return announcement_visible(
            active=obj.active,
            starts_on=obj.starts_on,
            ends_on=obj.ends_on,
            today=timezone.localdate(),
        )


class AnnouncementIn(Schema):
    title_ar: str = Field("", max_length=120)
    title_en: str = Field("", max_length=120)
    body_ar: str = Field("", max_length=600)
    body_en: str = Field("", max_length=600)
    starts_on: date | None = None
    ends_on: date | None = None
    active: bool = True
    sort_order: int = Field(0, ge=0, le=32767)


class AnnouncementPatch(PatchSchema):
    NULLABLE: ClassVar[frozenset[str]] = frozenset({"starts_on", "ends_on"})

    title_ar: str | None = Field(None, max_length=120)
    title_en: str | None = Field(None, max_length=120)
    body_ar: str | None = Field(None, max_length=600)
    body_en: str | None = Field(None, max_length=600)
    starts_on: date | None = None
    ends_on: date | None = None
    active: bool | None = None
    sort_order: int | None = Field(None, ge=0, le=32767)


MediaKind = Literal["hero", "gallery", "doctor"]


class CenterMediaOut(Schema):
    """An image of the website, uploaded by staff (PNG, JPEG or WebP, at most 2 MB)."""

    id: int
    kind: MediaKind
    content_type: str
    width: int
    height: int
    size_bytes: int
    alt_ar: str
    alt_en: str
    sort_order: int
    active: bool
    url: str = Field(..., description="Staff preview of the image (works with the site off)")
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_url(obj: Any) -> str:
        return f"/api/core/center-media/{obj.pk}/file?v={obj.updated_at:%Y%m%d%H%M%S%f}"


class CenterMediaPatch(PatchSchema):
    alt_ar: str | None = Field(None, max_length=200)
    alt_en: str | None = Field(None, max_length=200)
    sort_order: int | None = Field(None, ge=0, le=32767)
    active: bool | None = None


class CenterFaqOut(Schema):
    id: int
    question_ar: str
    question_en: str
    answer_ar: str
    answer_en: str
    sort_order: int
    active: bool
    updated_at: datetime


class CenterFaqIn(Schema):
    question_ar: str = Field("", max_length=200)
    question_en: str = Field("", max_length=200)
    answer_ar: str = Field("", max_length=1000)
    answer_en: str = Field("", max_length=1000)
    sort_order: int = Field(0, ge=0, le=32767)
    active: bool = True


class CenterFaqPatch(PatchSchema):
    question_ar: str | None = Field(None, max_length=200)
    question_en: str | None = Field(None, max_length=200)
    answer_ar: str | None = Field(None, max_length=1000)
    answer_en: str | None = Field(None, max_length=1000)
    sort_order: int | None = Field(None, ge=0, le=32767)
    active: bool | None = None


class TestimonialOut(Schema):
    id: int
    text_ar: str
    text_en: str
    author_ar: str
    author_en: str
    sort_order: int
    active: bool
    approved: bool = Field(..., description="Shown on the website only when approved and active")
    approved_by_name: str | None
    approved_at: datetime | None
    updated_at: datetime

    @staticmethod
    def resolve_approved(obj: Any) -> bool:
        return obj.approved_at is not None

    @staticmethod
    def resolve_approved_by_name(obj: Any) -> str | None:
        user = obj.approved_by
        if user is None:
            return None
        return str(user.display_name_en or user.display_name_ar or user.username)


class TestimonialIn(Schema):
    text_ar: str = Field("", max_length=400)
    text_en: str = Field("", max_length=400)
    author_ar: str = Field("", max_length=80)
    author_en: str = Field("", max_length=80)
    sort_order: int = Field(0, ge=0, le=32767)
    active: bool = True


class TestimonialPatch(PatchSchema):
    text_ar: str | None = Field(None, max_length=400)
    text_en: str | None = Field(None, max_length=400)
    author_ar: str | None = Field(None, max_length=80)
    author_en: str | None = Field(None, max_length=80)
    sort_order: int | None = Field(None, ge=0, le=32767)
    active: bool | None = None


class DoctorSiteProfileOut(Schema):
    """A doctor as the website administration sees it (no prices, no account data)."""

    id: int
    name_ar: str
    name_en: str
    specialty_ar: str
    specialty_en: str
    department_ar: str
    department_en: str
    active: bool
    qualifications_ar: str
    qualifications_en: str
    bio_ar: str
    bio_en: str
    photo_id: int | None
    online_bookable: bool = Field(..., description="Offered for online booking (ADR 0029 B)")
    has_schedule: bool = Field(..., description="Has active weekly hours (needed to book online)")

    @staticmethod
    def resolve_name_ar(obj: Any) -> str:
        return str(obj.user.display_name_ar)

    @staticmethod
    def resolve_has_schedule(obj: Any) -> bool:
        return bool(obj.schedules.filter(active=True).exists())

    @staticmethod
    def resolve_name_en(obj: Any) -> str:
        return str(obj.user.display_name_en)

    @staticmethod
    def resolve_department_ar(obj: Any) -> str:
        return str(obj.department.name_ar)

    @staticmethod
    def resolve_department_en(obj: Any) -> str:
        return str(obj.department.name_en)


class DoctorSiteProfilePatch(PatchSchema):
    NULLABLE: ClassVar[frozenset[str]] = frozenset({"photo_id"})

    qualifications_ar: str | None = Field(None, max_length=200)
    qualifications_en: str | None = Field(None, max_length=200)
    bio_ar: str | None = Field(None, max_length=400)
    bio_en: str | None = Field(None, max_length=400)
    photo_id: int | None = None
    online_bookable: bool | None = None


class SitePayerOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str
    active: bool
    show_on_site: bool


class SiteServiceOut(Schema):
    """A service's name and department only: the website never shows a price."""

    id: int
    code: str
    name_ar: str
    name_en: str
    kind: str
    department_id: int | None
    department_ar: str
    department_en: str
    active: bool
    show_on_site: bool

    @staticmethod
    def resolve_department_ar(obj: Any) -> str:
        return str(obj.department.name_ar) if obj.department else ""

    @staticmethod
    def resolve_department_en(obj: Any) -> str:
        return str(obj.department.name_en) if obj.department else ""


class ShowOnSiteIn(Schema):
    show_on_site: bool


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
    claims_second_approver: bool = Field(
        ..., description="Claims rebills and write-offs need a second person (ADR 0018)"
    )
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
    claims_second_approver: bool | None = Field(
        None, description="Omitted or null keeps the current value"
    )


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
