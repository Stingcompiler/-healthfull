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
    status: Literal["booked", "arrived", "no_show", "cancelled", "rescheduled"]
    doctor: PortalDoctorOut
    can_cancel: bool
    cancel_until: datetime | None


class PortalBookingRulesOut(Schema):
    max_open: int
    cancel_cutoff_hours: int
    horizon_days: int


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
