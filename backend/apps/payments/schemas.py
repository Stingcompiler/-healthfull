"""Schemas of ``/api/payments``: shifts, payments, transfers, refunds and handovers.

Money is a decimal string with two places (ARCHITECTURE 4.3). Shared shapes (names, users,
reasons, patients) come from ``apps.billing.schemas``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from ninja import Field, Schema

from apps.billing.schemas import (
    ApproverIn,
    CenterOut,
    MoneyIn,
    MoneyStr,
    NameOut,
    PatientSummaryOut,
    ReasonOut,
    UserRefOut,
)

PaymentMethodCode = Literal["cash", "bank_transfer", "qr", "card", "patient_credit"]
VerificationCode = Literal["pending", "confirmed", "rejected"]
RefundStatusCode = Literal["requested", "approved", "rejected", "paid"]
HandoverDestinationCode = Literal["next_shift", "safe", "bank_deposit", "supervisor"]
ReviewOutcomeCode = Literal["approved", "flagged"]


# --- shifts ----------------------------------------------------------------------------------


class ShiftReviewOut(Schema):
    outcome: ReviewOutcomeCode
    note: str
    reviewed_by: UserRefOut | None
    reviewed_at: datetime


class ShiftOut(Schema):
    id: int
    number: str
    status: Literal["open", "closed"]
    cashier: UserRefOut
    till: NameOut | None
    opened_at: datetime
    opening_float: MoneyStr
    closed_at: datetime | None
    closed_by: UserRefOut | None
    expected_cash: MoneyStr = Field(..., description="Live while open, frozen at close")
    counted_cash: MoneyStr | None
    variance: MoneyStr | None
    variance_reason: ReasonOut | None
    variance_note: str
    review: ShiftReviewOut | None


class MovementsOut(Schema):
    opening_float: MoneyStr
    cash_in: MoneyStr
    cash_refunds: MoneyStr
    handovers_out: MoneyStr
    handovers_in: MoneyStr


class CollectionOut(Schema):
    cash_confirmed: MoneyStr
    bank_confirmed: MoneyStr
    bank_pending: MoneyStr = Field(..., description="Never counted as collected (FLOW 9)")
    bank_rejected: MoneyStr
    credit_used: MoneyStr
    confirmed_total: MoneyStr


class ReportTransferOut(Schema):
    payment_id: int
    number: str
    amount: MoneyStr
    bank: str
    reference: str
    age_days: int | None


class ApproverTotalOut(Schema):
    user: UserRefOut | None
    amount: MoneyStr


class ReasonTotalOut(Schema):
    reason: ReasonOut | None
    code: str
    count: int
    amount: MoneyStr


class HandoverOut(Schema):
    id: int
    number: str
    shift_id: int
    shift_number: str
    destination: HandoverDestinationCode
    to_shift_id: int | None
    to_shift_number: str | None
    to_user: UserRefOut | None
    amount: MoneyStr
    bank_reference: str
    handed_by: UserRefOut | None
    handed_at: datetime
    received_by: UserRefOut | None
    received_at: datetime | None
    cancelled_by: UserRefOut | None
    cancelled_at: datetime | None
    cancel_note: str
    note: str


class ShiftReportOut(Schema):
    """The shift report (FLOW 9, FEATURES 7.3): confirmed money apart from pending."""

    shift: ShiftOut
    frozen: bool = Field(..., description="Served from the snapshot taken at close")
    movements: MovementsOut
    expected_cash: MoneyStr
    counted_cash: MoneyStr | None
    variance: MoneyStr | None
    collection: CollectionOut
    pending: list[ReportTransferOut]
    confirmed_transfers: list[ReportTransferOut]
    late_reversals: MoneyStr = Field(..., description="Earlier shifts' transfers rejected here")
    late_confirmations: MoneyStr
    refunds_paid: MoneyStr
    refunds: list[ReasonTotalOut]
    discounts: list[ApproverTotalOut]
    credit_notes: MoneyStr
    cancellations: list[ReasonTotalOut]
    credit_from_cancellations: MoneyStr
    credit_unallocated: MoneyStr
    handovers: list[HandoverOut]


class CurrentShiftOut(Schema):
    report: ShiftReportOut | None
    incoming_handovers: list[HandoverOut]


class ShiftOpenIn(Schema):
    opening_float: MoneyIn
    till: str | None = Field(None, max_length=20, description="Till code")
    note: str = Field("", max_length=500)


class ShiftCloseIn(Schema):
    counted: MoneyIn
    reason: str | None = Field(None, max_length=40, description="Variance reason code")
    note: str = Field("", max_length=1000)


class ShiftReviewIn(Schema):
    outcome: ReviewOutcomeCode = "approved"
    note: str = Field("", max_length=1000)


class ShiftListItemOut(Schema):
    shift: ShiftOut
    pending_count: int
    pending_amount: MoneyStr


# --- payments --------------------------------------------------------------------------------


class AllocationIn(Schema):
    invoice_id: int
    amount: MoneyIn


class OverrideIn(Schema):
    """Accept a reference already used for the bank (FEATURES 6.2): reason and a supervisor."""

    reason: str = Field(..., min_length=1, max_length=40)
    note: str = Field("", max_length=1000)
    approver: ApproverIn | None = Field(
        None, description="A supervisor's credentials; omit when the cashier may override"
    )


class PaymentIn(Schema):
    patient_id: int
    method: PaymentMethodCode
    amount: MoneyIn
    bank: str | None = Field(None, max_length=20, description="Bank code (transfer, QR, card)")
    reference: str = Field("", max_length=100)
    transfer_date: date | None = None
    sender_name: str = Field("", max_length=200)
    allocations: list[AllocationIn] | None = None
    auto: bool = Field(False, description="Allocate to the oldest open invoices")
    note: str = Field("", max_length=500)
    override: OverrideIn | None = None


class AllocateIn(Schema):
    allocations: list[AllocationIn] | None = None
    auto: bool = False


class AllocationOut(Schema):
    id: int
    invoice_id: int
    invoice_number: str | None
    kind: str
    amount: MoneyStr
    created_at: datetime


class PaymentOut(Schema):
    id: int
    number: str
    shift_id: int
    shift_number: str
    shift_status: str
    patient: PatientSummaryOut
    method: PaymentMethodCode
    amount: MoneyStr
    bank: NameOut | None
    reference: str
    transfer_date: date | None
    sender_name: str
    verification: VerificationCode
    verified_by: UserRefOut | None
    verified_at: datetime | None
    rejection_reason: ReasonOut | None
    rejection_note: str
    duplicate_override: bool
    duplicate_of_number: str | None
    override_by: UserRefOut | None
    override_reason: ReasonOut | None
    override_note: str
    reversal_of_number: str | None
    reversal_number: str | None
    note: str
    created_by: UserRefOut | None
    created_at: datetime
    age_days: int
    allocations: list[AllocationOut]
    unallocated: MoneyStr


class RejectionOut(Schema):
    payment: PaymentOut
    reversal: PaymentOut | None
    uncovered: MoneyStr


class ConfirmIn(Schema):
    note: str = Field(..., min_length=1, max_length=1000, description="What was checked")


class RejectIn(Schema):
    reason: str = Field(..., min_length=1, max_length=40)
    note: str = Field("", max_length=1000)


class ReceiptLineOut(Schema):
    description_ar: str
    description_en: str
    quantity: int
    patient_share: MoneyStr


class ReceiptInvoiceOut(Schema):
    id: int
    number: str | None
    amount: MoneyStr
    outstanding: MoneyStr
    lines: list[ReceiptLineOut]


class ReceiptOut(Schema):
    center: CenterOut
    payment: PaymentOut
    invoices: list[ReceiptInvoiceOut]
    cashier: UserRefOut | None
    verify_code: str = Field(..., description="Encoded in the receipt's QR (FEATURES 6.9)")


# --- transfers queue -------------------------------------------------------------------------


class TransferOut(Schema):
    payment: PaymentOut
    cashier: UserRefOut | None


# --- refunds ---------------------------------------------------------------------------------


class RefundIn(Schema):
    credit_note_id: int
    patient_id: int | None = Field(None, description="Default: the credit note's patient")
    amount: MoneyIn
    reason: str = Field(..., min_length=1, max_length=40)
    note: str = Field("", max_length=1000)


class DecisionIn(Schema):
    note: str = Field("", max_length=1000)


class RefundOut(Schema):
    id: int
    number: str
    patient: PatientSummaryOut
    amount: MoneyStr
    method: str
    credit_note_id: int | None
    credit_note_number: str | None
    reason: ReasonOut | None
    reason_note: str
    status: RefundStatusCode
    requested_by: UserRefOut | None
    requested_at: datetime
    decided_by: UserRefOut | None
    decided_at: datetime | None
    decision_note: str
    shift_number: str | None
    paid_by: UserRefOut | None
    paid_at: datetime | None


# --- handovers -------------------------------------------------------------------------------


class HandoverIn(Schema):
    amount: MoneyIn
    destination: HandoverDestinationCode
    to_shift_id: int | None = None
    bank_reference: str = Field("", max_length=100)
    note: str = Field("", max_length=500)


class HandoverCancelIn(Schema):
    note: str = Field(..., min_length=1, max_length=500)


class OpenShiftRefOut(Schema):
    id: int
    number: str
    cashier: UserRefOut
    opened_at: datetime
