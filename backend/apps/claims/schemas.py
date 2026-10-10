"""Schemas of ``/api/claims`` (FEATURES 11.2-11.7).

Money is a decimal string with two places (``"10000.00"``, ARCHITECTURE 4.3); amounts sent by
the client are strings parsed strictly by ``domain.money.money``. django-ninja publishes one
OpenAPI component per class name, so every class here starts with ``Claim`` and never
collides with another app's (guarded by ``api/tests/test_main.py``).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from ninja import Field, Schema

#: A money amount as the API sends it: two decimal places, e.g. "15000.00".
ClaimMoney = Annotated[str, Field(pattern=r"^-?[0-9]+\.[0-9]{2}$", examples=["15000.00"])]
#: A money amount sent by the client (Arabic-Indic digits and separator accepted; a third
#: decimal is refused, never rounded away; everything else is judged by ``domain.money``).
ClaimMoneyIn = Annotated[
    str,
    Field(
        min_length=1,
        max_length=20,
        pattern=r"^[^.٫]*(?:[.٫]\S{0,2})?\s*$",
        examples=["15000", "2500.50"],
    ),
]

ClaimStatusCode = Literal["draft", "submitted", "responded", "closed", "void"]
ClaimLineStatusCode = Literal["pending", "accepted", "rejected", "partial", "withdrawn"]
#: The line's stage in the payer cycle (``domain.claims.ClaimLineStatus``).
ClaimLineStage = Literal[
    "claimed",
    "accepted",
    "rejected",
    "partially_accepted",
    "paid",
    "rebilled",
    "written_off",
    "voided",
]
ClaimResolutionCode = Literal["none", "rebilled", "written_off"]
ClaimOutcome = Literal["accepted", "rejected", "partial"]
ClaimPayerPaymentMethod = Literal["bank_transfer", "cheque", "cash"]
#: Where a payer payment's money stands: in the bank, in a cashier's drawer, a cheque not
#: cleared yet, or reversed (bounced).
ClaimPayerPaymentStanding = Literal["bank", "cash", "cheque_pending", "cheque_cleared", "reversed"]


# --- references ---------------------------------------------------------------------------


class ClaimNameOut(Schema):
    """A coded row (payer, bank)."""

    id: int
    code: str
    name_ar: str
    name_en: str


class ClaimPayerOut(ClaimNameOut):
    kind: str
    claim_period: str
    contract_no: str
    active: bool


class ClaimUserOut(Schema):
    id: int
    username: str
    full_name_ar: str
    full_name_en: str


class ClaimReasonOut(Schema):
    code: str
    label_ar: str
    label_en: str
    requires_note: bool


class ClaimPatientOut(Schema):
    id: int
    file_no: str
    full_name_ar: str
    full_name_en: str


class ClaimShiftOut(Schema):
    id: int
    number: str


class ClaimOptionsOut(Schema):
    """What the claim screens choose from: payers, banks, write-off reasons, and the viewer's
    open shift (payer cash goes into it, ARCHITECTURE 4.7)."""

    payers: list[ClaimPayerOut]
    banks: list[ClaimNameOut]
    write_off_reasons: list[ClaimReasonOut]
    open_shift: ClaimShiftOut | None


# --- receivables and aging (FEATURES 11.2, 11.7) ------------------------------------------


class ClaimStagesOut(Schema):
    """A payer share by stage. ``receivable`` (AR_PAYER) = accrued + claimed + accepted unpaid
    + rejected unresolved; ``collected`` is the only part that is money (invariant 7)."""

    accrued: ClaimMoney
    claimed: ClaimMoney
    accepted_unpaid: ClaimMoney
    rejected_unresolved: ClaimMoney
    receivable: ClaimMoney
    collected: ClaimMoney
    rebilled: ClaimMoney
    written_off: ClaimMoney


class ClaimAgingOut(Schema):
    """The outstanding receivable by days since invoice approval."""

    days_0_30: ClaimMoney
    days_31_60: ClaimMoney
    days_61_90: ClaimMoney
    days_over_90: ClaimMoney
    total: ClaimMoney


class ClaimReceivableOut(Schema):
    payer: ClaimPayerOut
    stages: ClaimStagesOut
    aging: ClaimAgingOut


class ClaimReceivablesOut(Schema):
    as_of: date
    items: list[ClaimReceivableOut]
    totals: ClaimStagesOut


class ClaimAgingRowOut(Schema):
    payer: ClaimPayerOut
    aging: ClaimAgingOut


class ClaimAgingReportOut(Schema):
    as_of: date
    items: list[ClaimAgingRowOut]
    totals: ClaimAgingOut


# --- accrued lines and batches (FEATURES 11.3) --------------------------------------------


class ClaimServiceFields(Schema):
    """What the claim shows of the invoice line a payer share comes from."""

    invoice_line_id: int
    invoice_id: int
    invoice_number: str
    approved_on: date
    patient: ClaimPatientOut
    card_number: str
    service_code: str
    description_ar: str
    description_en: str
    quantity: int
    gross: ClaimMoney
    pre_approval_ref: str


class ClaimAccruedLineOut(ClaimServiceFields):
    """An unclaimed payer share: ``amount`` is what may be claimed."""

    amount: ClaimMoney
    age_days: int


class ClaimAccruedOut(Schema):
    payer: ClaimPayerOut
    period_start: date | None
    period_end: date | None
    items: list[ClaimAccruedLineOut]
    total: ClaimMoney


class ClaimBuildIn(Schema):
    payer_id: int
    period_start: date
    period_end: date
    invoice_line_ids: list[int] | None = Field(
        None, description="The accrued lines to claim; all of the period when omitted."
    )
    note: str = Field("", max_length=500)


class ClaimSummaryOut(Schema):
    id: int
    number: str
    payer: ClaimNameOut
    period_start: date
    period_end: date
    status: ClaimStatusCode
    claimed_total: ClaimMoney
    accepted_total: ClaimMoney
    rejected_total: ClaimMoney
    paid_total: ClaimMoney
    unpaid_total: ClaimMoney = Field(..., description="Accepted, not paid, not written off.")
    receivable: ClaimMoney
    line_count: int
    created_at: datetime
    submitted_at: datetime | None
    response_at: datetime | None
    closed_at: datetime | None


class ClaimLineOut(ClaimServiceFields):
    id: int
    amount_claimed: ClaimMoney
    status: ClaimLineStatusCode
    stage: ClaimLineStage
    accepted_amount: ClaimMoney
    rejected_amount: ClaimMoney
    paid: ClaimMoney
    written_off_amount: ClaimMoney
    unpaid: ClaimMoney
    unresolved_rejection: ClaimMoney
    receivable: ClaimMoney
    payer_reason: str
    payer_reference: str
    responded_at: datetime | None
    resolution: ClaimResolutionCode
    resolution_reason: ClaimReasonOut | None
    resolution_note: str
    resolved_by: ClaimUserOut | None
    resolved_at: datetime | None
    written_off_reason: ClaimReasonOut | None
    written_off_note: str
    withdraw_note: str


class ClaimPaymentRefOut(Schema):
    """A payer payment allocated to this claim (the claim's share of it)."""

    id: int
    number: str
    received_on: date
    method: ClaimPayerPaymentMethod
    amount: ClaimMoney
    reversed: bool


class ClaimDetailOut(ClaimSummaryOut):
    note: str
    created_by: ClaimUserOut
    submitted_by: ClaimUserOut | None
    lines: list[ClaimLineOut]
    payments: list[ClaimPaymentRefOut]


class ClaimVoidIn(Schema):
    note: str = Field(..., min_length=1, max_length=500)


class ClaimResponseIn(Schema):
    claim_line_id: int
    outcome: ClaimOutcome
    accepted: ClaimMoneyIn | None = Field(None, description="The accepted part of a partial.")
    reason: str = Field("", max_length=300, description="The payer's reason for a rejection.")
    reference: str = Field("", max_length=100)


class ClaimResponsesIn(Schema):
    responses: list[ClaimResponseIn] = Field(..., min_length=1)


class ClaimResolveIn(Schema):
    resolution: Literal["rebilled", "written_off"]
    reason: str = Field(..., min_length=1, max_length=40, description="A write-off reason code.")
    note: str = Field("", max_length=500)


class ClaimShortfallIn(Schema):
    amount: ClaimMoneyIn
    reason: str = Field(..., min_length=1, max_length=40)
    note: str = Field("", max_length=500)


class ClaimPayerOutDetail(ClaimPayerOut):
    address: str
    contact_name: str
    phone: str
    email: str


class ClaimCenterOut(Schema):
    name_ar: str
    name_en: str
    address: str
    phone: str
    registration_no: str
    tax_no: str


class ClaimPrintOut(Schema):
    center: ClaimCenterOut
    payer: ClaimPayerOutDetail
    claim: ClaimDetailOut


# --- payer payments (FEATURES 11.6) -------------------------------------------------------


class ClaimPayableOut(Schema):
    """A claim with accepted money the payer still owes (a payment can be allocated to it)."""

    id: int
    number: str
    period_start: date
    period_end: date
    accepted_total: ClaimMoney
    paid_total: ClaimMoney
    unpaid_total: ClaimMoney


class ClaimAllocationIn(Schema):
    claim_id: int
    amount: ClaimMoneyIn


class ClaimLineAllocationIn(Schema):
    claim_line_id: int
    amount: ClaimMoneyIn


class ClaimPayerPaymentIn(Schema):
    payer_id: int
    amount: ClaimMoneyIn
    method: ClaimPayerPaymentMethod = "bank_transfer"
    bank_id: int | None = None
    reference: str = Field("", max_length=100)
    received_on: date
    claims: list[ClaimAllocationIn] | None = Field(
        None,
        description="Amounts per claim; with neither claims nor lines, oldest claims first.",
    )
    lines: list[ClaimLineAllocationIn] | None = None
    note: str = Field("", max_length=500)


class ClaimPayerAllocationOut(Schema):
    claim_id: int
    claim_number: str
    claim_line_id: int | None
    amount: ClaimMoney


class ClaimPayerPaymentOut(Schema):
    id: int
    number: str
    payer: ClaimNameOut
    amount: ClaimMoney
    method: ClaimPayerPaymentMethod
    standing: ClaimPayerPaymentStanding
    bank: ClaimNameOut | None
    reference: str
    received_on: date
    shift: ClaimShiftOut | None
    note: str
    recorded_by: ClaimUserOut
    recorded_at: datetime
    cleared_at: datetime | None
    reversed_at: datetime | None
    reverse_note: str
    allocations: list[ClaimPayerAllocationOut]


class ClaimNoteIn(Schema):
    note: str = Field("", max_length=500)
