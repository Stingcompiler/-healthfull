"""Schemas of ``/api/billing`` (and the shared shapes of the cashier screens).

Money is a decimal string with two places (``"10000.00"``, ARCHITECTURE 4.3); amounts sent by
the client are strings too and are parsed strictly by ``domain.money.money``. Nothing here
carries a price to a role without billing permissions: every operation that returns these
shapes requires a ``billing.*`` or ``payments.*`` code, which doctors never hold.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from ninja import Field, Schema

#: A money amount as the API sends it: two decimal places, e.g. "15000.00" (may be negative).
MoneyStr = Annotated[str, Field(pattern=r"^-?[0-9]+\.[0-9]{2}$", examples=["15000.00"])]
#: A money amount sent by the client: digits with an optional decimal part (Arabic-Indic too).
MoneyIn = Annotated[str, Field(min_length=1, max_length=20, examples=["15000", "2500.50"])]

LineState = Literal["requested", "invoiced", "paid", "performed", "cancelled"]
DocStatus = Literal["draft", "approved", "void"]
ReasonCategoryCode = Literal[
    "discount",
    "credit_note",
    "line_cancel",
    "override",
    "variance",
    "refund",
    "transfer_reject",
    "perform_first",
]


class NameOut(Schema):
    """A coded catalog row (payer, department, bank, till, service)."""

    id: int
    code: str
    name_ar: str
    name_en: str


class ServiceRefOut(NameOut):
    kind: str


class BillingUserRefOut(Schema):
    id: int
    username: str
    full_name_ar: str
    full_name_en: str


class BillingReasonOut(Schema):
    code: str
    label_ar: str
    label_en: str
    requires_note: bool


class PatientSummaryOut(Schema):
    id: int
    file_no: str
    full_name_ar: str
    full_name_en: str
    sex: str
    date_of_birth: date | None
    phone: str
    is_incomplete: bool
    merged_into_id: int | None


class BillingBalanceOut(Schema):
    """The person's money position (FEATURES 1.5), every merged file included."""

    credit: MoneyStr = Field(..., description="Pooled patient credit; negative when owed")
    spendable: MoneyStr = Field(..., description="Credit that may be spent or refunded now")
    pending: MoneyStr = Field(..., description="Unallocated money of pending transfers")
    outstanding: MoneyStr = Field(..., description="Patient money still owed on invoices")


class BillingOpenInvoiceOut(Schema):
    id: int
    number: str
    visit_id: int
    outstanding: MoneyStr


class ApproverIn(Schema):
    """A supervisor's credentials typed into the cashier's approval dialog (ADR 0007)."""

    username: str = Field(..., min_length=1, max_length=150)
    password: str = Field(..., min_length=1, max_length=256)


# --- lookup ----------------------------------------------------------------------------------


class LookupVisitOut(Schema):
    id: int
    number: str
    visit_type: str
    status: str
    created_at: datetime
    department: NameOut | None
    doctor: BillingUserRefOut | None
    payer: NameOut | None
    unbilled_count: int
    draft_invoice_count: int
    outstanding: MoneyStr


class LookupPatientOut(Schema):
    patient: PatientSummaryOut
    visits: list[LookupVisitOut]
    balance: BillingBalanceOut


class LookupOut(Schema):
    items: list[LookupPatientOut]


# --- lines and invoices ----------------------------------------------------------------------


class ServiceLineOut(Schema):
    """A visit's service line as the cashier sees it."""

    id: int
    service: ServiceRefOut
    quantity: int
    state: LineState
    billing_status: str
    fulfilment_status: str
    payer: NameOut | None
    authorized: bool
    order_source: str
    ordered_at: datetime
    pre_approval_ref: str
    draft_invoice_id: int | None = Field(..., description="The draft invoice holding the line")


class InvoiceLineOut(Schema):
    id: int
    line_no: int
    service_line_id: int
    service: ServiceRefOut
    description_ar: str
    description_en: str
    quantity: int
    unit_price: MoneyStr
    gross: MoneyStr
    discount: MoneyStr
    discount_percent: str | None
    discount_reason: BillingReasonOut | None
    discount_note: str
    discount_approved_by: BillingUserRefOut | None
    payer: NameOut | None
    payer_share: MoneyStr
    patient_share: MoneyStr
    excluded: bool
    pre_approval_ref: str
    requires_pre_approval: bool
    state: LineState
    credited_quantity: int
    outstanding: MoneyStr | None = Field(..., description="Patient money owed (approved only)")


class InvoicePaymentOut(Schema):
    """Money applied to the invoice by one payment (allocation rows summed, signed)."""

    payment_id: int
    number: str
    method: str
    verification: str
    amount: MoneyStr


class CreditNoteRefOut(Schema):
    id: int
    number: str | None
    status: DocStatus
    gross_total: MoneyStr
    patient_total: MoneyStr
    created_at: datetime


class InvoiceOut(Schema):
    id: int
    number: str | None
    status: DocStatus
    visit_id: int
    visit_number: str
    patient: PatientSummaryOut
    priced_on: date | None
    created_at: datetime
    created_by: BillingUserRefOut | None
    approved_at: datetime | None
    approved_by: BillingUserRefOut | None
    gross_total: MoneyStr
    discount_total: MoneyStr
    payer_total: MoneyStr
    patient_total: MoneyStr
    outstanding: MoneyStr | None
    paid: MoneyStr | None
    lines: list[InvoiceLineOut]
    payments: list[InvoicePaymentOut]
    credit_notes: list[CreditNoteRefOut]


class VisitRefOut(Schema):
    id: int
    number: str
    visit_type: str
    status: str
    created_at: datetime
    department: NameOut | None
    doctor: BillingUserRefOut | None
    payer: NameOut | None
    card_number: str


class VisitBillingOut(Schema):
    """Everything the billing panel shows for one visit (FLOW step 4)."""

    patient: PatientSummaryOut
    visit: VisitRefOut
    payers: list[NameOut] = Field(..., description="Payers a line may be billed to (valid cover)")
    unbilled: list[ServiceLineOut]
    drafts: list[InvoiceOut]
    invoices: list[InvoiceOut]
    balance: BillingBalanceOut
    open_invoices: list[BillingOpenInvoiceOut] = Field(..., description="Person-wide, oldest first")


class InvoiceCreateIn(Schema):
    visit_id: int
    line_ids: list[int] | None = Field(None, description="Default: every unbilled line")


class DiscountIn(Schema):
    reason: str = Field(..., min_length=1, max_length=40)
    note: str = Field("", max_length=500)
    amount: MoneyIn | None = None
    percent: MoneyIn | None = None
    approver: ApproverIn | None = Field(
        None, description="A supervisor approving above the cashier's limit"
    )


class PreApprovalIn(Schema):
    reference: str = Field(..., max_length=100)


class LinePayerIn(Schema):
    payer_id: int | None = Field(..., description="null bills the line to the patient (cash)")
    note: str = Field(..., min_length=1, max_length=500)


class LineCancelIn(Schema):
    reason: str = Field(..., min_length=1, max_length=40)
    note: str = Field("", max_length=500)


class VoidIn(Schema):
    note: str = Field(..., min_length=1, max_length=500)


# --- credit notes ----------------------------------------------------------------------------


class CreditNoteLineIn(Schema):
    invoice_line_id: int
    quantity: int = Field(..., ge=1)


class CreditNoteIn(Schema):
    lines: list[CreditNoteLineIn] = Field(..., min_length=1)
    reason: str = Field(..., min_length=1, max_length=40)
    note: str = Field("", max_length=1000)


class CreditNoteApproveIn(Schema):
    rebill: bool = Field(False, description="Re-bill each fully credited line (a correction)")
    open_refund: bool = Field(True, description="Open a refund request for released money")


class CreditNoteLineOut(Schema):
    id: int
    line_no: int
    invoice_line_id: int
    service: ServiceRefOut
    quantity: int
    gross: MoneyStr
    discount: MoneyStr
    payer_share: MoneyStr
    patient_share: MoneyStr
    cancels_service_line: bool


class RefundRefOut(Schema):
    id: int
    number: str
    status: str
    amount: MoneyStr


class CreditNoteOut(Schema):
    id: int
    number: str | None
    status: DocStatus
    invoice_id: int
    invoice_number: str | None
    patient: PatientSummaryOut
    reason: BillingReasonOut
    reason_note: str
    created_by: BillingUserRefOut | None
    created_at: datetime
    approved_by: BillingUserRefOut | None
    approved_at: datetime | None
    gross_total: MoneyStr
    discount_total: MoneyStr
    payer_total: MoneyStr
    patient_total: MoneyStr
    released: MoneyStr = Field(..., description="Patient money it turned into credit")
    refundable: MoneyStr = Field(..., description="Released money not yet refunded")
    lines: list[CreditNoteLineOut]
    refunds: list[RefundRefOut]


class CreditOutcomeOut(Schema):
    credit_note: CreditNoteOut
    deallocated: MoneyStr
    refund: RefundRefOut | None
    replacement_line_ids: list[int]


class BillingCenterOut(Schema):
    name_ar: str
    name_en: str
    address: str
    phone: str
    registration_no: str
    tax_no: str


class InvoicePrintOut(Schema):
    center: BillingCenterOut
    invoice: InvoiceOut
