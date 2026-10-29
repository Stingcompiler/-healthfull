"""Schemas of ``/api/portal`` (FEATURES 15.1, 15.2). Every class name starts with ``Portal``
(OpenAPI components are keyed by class name across apps). Money is a decimal string."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from ninja import Field, Schema

PortalMoney = Annotated[str, Field(pattern=r"^-?[0-9]+\.[0-9]{2}$", examples=["15000.00"])]
PortalReceiptStatus = Literal["valid", "pending", "void"]


class PortalLoginIn(Schema):
    file_no: str = Field(..., min_length=1, max_length=40)
    phone: str = Field(..., min_length=1, max_length=30)
    code: str = Field(..., min_length=1, max_length=20)


class PortalMeOut(Schema):
    file_no: str
    full_name_ar: str
    full_name_en: str
    sex: str
    date_of_birth: date | None
    phone_masked: str
    idle_seconds: int = Field(..., description="The session ends after this long without use")


class PortalSessionOut(Schema):
    signed_in: bool
    me: PortalMeOut | None


class PortalDoctorOut(Schema):
    id: int
    name_ar: str
    name_en: str
    specialty_ar: str
    specialty_en: str
    department_ar: str
    department_en: str


class PortalAppointmentOut(Schema):
    id: int
    starts_at: datetime
    ends_at: datetime
    status: Literal["requested", "booked", "arrived", "no_show", "cancelled", "rescheduled"]
    display_status: Literal[
        "awaiting_approval",
        "confirmed",
        "received",
        "moved",
        "cancelled_by_you",
        "cancelled_by_center",
        "declined",
        "expired",
        "missed",
    ] = Field(..., description="What the patient is told (domain.portal_status)")
    expires_at: datetime | None = Field(
        ..., description="A request waiting for reception lapses then (ADR 0029 A8)"
    )
    doctor: PortalDoctorOut
    can_cancel: bool
    cancel_until: datetime | None
    can_reschedule: bool
    reschedule_until: datetime | None


class PortalBookingRulesOut(Schema):
    max_open: int
    cancel_cutoff_hours: int
    horizon_days: int
    reschedule_allowed: bool
    reschedule_cutoff_hours: int
    require_approval: bool


class PortalAppointmentsOut(Schema):
    upcoming: list[PortalAppointmentOut]
    past: list[PortalAppointmentOut]
    rules: PortalBookingRulesOut


class PortalSlotOut(Schema):
    starts_at: datetime
    ends_at: datetime


class PortalSlotsOut(Schema):
    doctor: PortalDoctorOut
    day: date
    slots: list[PortalSlotOut]


class PortalBookIn(Schema):
    doctor_id: int
    starts_at: datetime = Field(..., description="Exactly a `starts_at` from the slots list")


class PortalRescheduleIn(Schema):
    starts_at: datetime = Field(..., description="Exactly a `starts_at` from the slots list")
    doctor_id: int | None = Field(None, description="Another doctor; default the same one")


class PortalResultSummaryOut(Schema):
    line_id: int
    test_name_ar: str
    test_name_en: str
    ordered_at: datetime
    approved_at: datetime | None
    amended: bool = Field(..., description="This approved result corrects an earlier one")
    abnormal: bool


class PortalCenterOut(Schema):
    name_ar: str
    name_en: str
    address: str
    phone: str


class PortalHoursOut(Schema):
    weekday: int = Field(..., description="0 = Monday ... 6 = Sunday")
    closed: bool
    opens: str | None = Field(..., description="HH:MM")
    closes: str | None = Field(..., description="HH:MM")


class PortalTodayOut(Schema):
    weekday: int
    state: Literal["open", "opens_later", "closed_now", "closed_today"]
    opens: str | None
    closes: str | None


class PortalPublicServiceOut(Schema):
    """A service's name only: the website never shows a price (ADR 0023, 0029 A5)."""

    id: int
    name_ar: str
    name_en: str


class PortalPublicDepartmentOut(Schema):
    id: int
    name_ar: str
    name_en: str
    services: list[PortalPublicServiceOut] = Field(
        ..., description="Names of the services the center shows under this department"
    )


class PortalPublicImageOut(Schema):
    """An image the center uploaded (never an external URL); the URL changes with the image."""

    id: int
    url: str
    alt_ar: str
    alt_en: str
    width: int
    height: int


class PortalFacilityOut(Schema):
    name_ar: str
    name_en: str


class PortalReasonOut(Schema):
    title_ar: str
    title_en: str
    text_ar: str
    text_en: str


class PortalPublicPayerOut(Schema):
    id: int
    name_ar: str
    name_en: str


class PortalFaqOut(Schema):
    id: int
    question_ar: str
    question_en: str
    answer_ar: str
    answer_en: str


class PortalTestimonialOut(Schema):
    """Typed by staff and approved by a manager; never submitted by the public."""

    id: int
    text_ar: str
    text_en: str
    author_ar: str
    author_en: str


class PortalClinicDayOut(Schema):
    weekday: int
    starts: str = Field(..., description="HH:MM")
    ends: str = Field(..., description="HH:MM")


class PortalPublicDoctorOut(Schema):
    id: int
    name_ar: str
    name_en: str
    specialty_ar: str
    specialty_en: str
    department_id: int
    department_ar: str
    department_en: str
    clinic_days: list[PortalClinicDayOut]
    qualifications_ar: str
    qualifications_en: str
    bio_ar: str
    bio_en: str
    photo: PortalPublicImageOut | None


class PortalAnnouncementOut(Schema):
    id: int
    title_ar: str
    title_en: str
    body_ar: str
    body_en: str
    starts_on: date | None
    ends_on: date | None


class PortalCenterIdentityOut(Schema):
    """The center's name and logo only; public even while the center website is off."""

    name_ar: str
    name_en: str
    logo_url: str | None


class PortalCenterPageOut(Schema):
    """The public center page: identity and the sections the center chose to show. A hidden
    or empty section comes back empty. Never prices, never staff other than the doctors."""

    name_ar: str
    name_en: str
    logo_url: str | None = Field(..., description="Public logo, changes with the logo")
    about_ar: str
    about_en: str
    hours: list[PortalHoursOut]
    today: PortalTodayOut | None
    departments: list[PortalPublicDepartmentOut]
    doctors: list[PortalPublicDoctorOut]
    announcements: list[PortalAnnouncementOut]
    phone: str
    phone_uri: str = Field(..., description="tel: link of the phone, or empty")
    whatsapp: str = Field(..., description="International digits for https://wa.me/<digits>")
    email: str
    address: str
    directions_ar: str
    directions_en: str
    maps_url: str = Field(..., description="A plain https map link, or empty")
    hero_title_ar: str
    hero_title_en: str
    hero_text_ar: str
    hero_text_en: str
    hero_image: PortalPublicImageOut | None
    gallery: list[PortalPublicImageOut]
    facilities: list[PortalFacilityOut]
    reasons: list[PortalReasonOut]
    insurance: list[PortalPublicPayerOut] = Field(..., description="Accepted insurers, names only")
    faq: list[PortalFaqOut]
    testimonials: list[PortalTestimonialOut]
    accessibility_ar: str
    accessibility_en: str
    privacy_ar: str
    privacy_en: str
    cancellation_policy_ar: str
    cancellation_policy_en: str


class PortalPatientHeadOut(Schema):
    file_no: str
    full_name_ar: str
    full_name_en: str
    sex: str
    date_of_birth: date | None


class PortalPersonNameOut(Schema):
    name_ar: str
    name_en: str


class PortalResultValueOut(Schema):
    parameter_code: str
    name_ar: str
    name_en: str
    value: str
    unit: str
    reference_low: str | None
    reference_high: str | None
    reference_text: str
    flag: str


class PortalResultOut(PortalResultSummaryOut):
    center: PortalCenterOut
    patient: PortalPatientHeadOut
    visit_number: str
    ordered_by: PortalPersonNameOut | None
    comment: str
    values: list[PortalResultValueOut]


class PortalPrescriptionItemOut(Schema):
    line_id: int
    name_ar: str
    name_en: str
    dose: str
    route: str
    frequency_code: str
    frequency_per_day: str | None
    duration_days: int | None
    as_needed: bool
    instructions: str
    quantity: int
    state: Literal["dispensed", "partly_dispensed", "not_dispensed"]


class PortalPrescriptionVisitOut(Schema):
    visit_number: str
    date: date
    prescriber: PortalPersonNameOut | None
    items: list[PortalPrescriptionItemOut]


class PortalLabInstructionOut(Schema):
    line_id: int
    test_name_ar: str
    test_name_en: str
    instructions_ar: str
    instructions_en: str
    ordered_at: datetime


class PortalPrescriptionsOut(Schema):
    visits: list[PortalPrescriptionVisitOut]
    lab_instructions: list[PortalLabInstructionOut]


class PortalInvoiceOut(Schema):
    id: int
    number: str
    date: date | None
    visit_number: str
    patient_due: PortalMoney = Field(..., description="The patient's share after credits")
    paid: PortalMoney
    outstanding: PortalMoney


class PortalInvoiceLineOut(Schema):
    description_ar: str
    description_en: str
    quantity: int
    patient_share: PortalMoney


class PortalInvoiceReceiptOut(Schema):
    id: int
    number: str
    date: date
    amount: PortalMoney


class PortalInvoiceDetailOut(PortalInvoiceOut):
    center: PortalCenterOut
    lines: list[PortalInvoiceLineOut]
    receipts: list[PortalInvoiceReceiptOut]


class PortalReceiptOut(Schema):
    id: int
    number: str
    date: date
    amount: PortalMoney
    method: str
    status: PortalReceiptStatus


class PortalReceiptInvoiceOut(Schema):
    id: int
    number: str
    amount: PortalMoney


class PortalReceiptDetailOut(PortalReceiptOut):
    center: PortalCenterOut
    invoices: list[PortalReceiptInvoiceOut]
    to_credit: PortalMoney


class PortalBalanceOut(Schema):
    outstanding: PortalMoney
    credit: PortalMoney
    pending: PortalMoney = Field(..., description="Transfers the bank has not confirmed yet")
    open_invoices: int


class PortalSummaryOut(Schema):
    next_appointment: PortalAppointmentOut | None
    latest_results: list[PortalResultSummaryOut]
    balance: PortalBalanceOut


class PortalVerifyOut(Schema):
    """The public check of a printed receipt: nothing that identifies a patient."""

    center_name_ar: str
    center_name_en: str
    receipt_number: str
    date: date
    amount: PortalMoney
    status: PortalReceiptStatus
    patient_initials: str


class PortalIssueCodeIn(Schema):
    payment_id: int


class PortalIssuedCodeOut(Schema):
    code: str = Field(..., description="Shown once; only its hash is stored")
    expires_at: datetime
    file_no: str


class PortalCodeSlipOut(Schema):
    """A code issued at reception for the printed slip (shown once)."""

    code: str = Field(..., description="Shown once; only its hash is stored")
    expires_at: datetime
    file_no: str
    full_name_ar: str
    full_name_en: str


class PortalStaffRefOut(Schema):
    id: int
    full_name_ar: str
    full_name_en: str


class PortalAccessCodeRowOut(Schema):
    """An issued code as staff see it: its state, never the code."""

    id: int
    state: Literal["active", "expired", "locked", "revoked"]
    created_at: datetime
    created_by: PortalStaffRefOut
    expires_at: datetime
    last_used_at: datetime | None
    failed_attempts: int
    revoked_at: datetime | None
    revoked_by: PortalStaffRefOut | None
    revoke_note: str


class PortalAccessCodesOut(Schema):
    patient_id: int = Field(..., description="The file the codes belong to (survivor of a merge)")
    file_no: str
    has_phone: bool = Field(..., description="A code needs a phone on the file to sign in with")
    codes: list[PortalAccessCodeRowOut]


class PortalRevokeCodeIn(Schema):
    note: str = Field(..., min_length=1, max_length=300, description="Why the code is revoked")
