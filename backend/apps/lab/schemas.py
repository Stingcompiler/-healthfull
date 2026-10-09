"""Schemas of ``/api/lab``: work list, samples and labels, results, approval, catalog, reports.

Every class name starts with ``Lab``: ninja keys OpenAPI components by class name, so names
must be unique across apps (``api/tests/test_main.py``). Decimal limits and values travel as
strings (``"13.5"``); the lab screens never do arithmetic on them beyond previewing a flag.
No price reaches these shapes.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from ninja import Field, Schema

LabStage = Literal["to_collect", "to_receive", "to_enter", "to_approve", "done", "cancelled"]
LabWorklistFilter = Literal["open", "to_collect", "to_receive", "to_enter", "to_approve", "done"]
LabSampleTypeCode = Literal[
    "whole_blood", "serum", "plasma", "urine", "stool", "swab", "sputum", "csf", "fluid", "other"
]
LabSampleStatus = Literal["collected", "received", "rejected"]
LabValueTypeCode = Literal["numeric", "text", "choice", "pos_neg"]
LabRangeSexCode = Literal["any", "male", "female"]
LabFlagCode = Literal["normal", "low", "high", "critical_low", "critical_high", "abnormal", "none"]
LabVersionStatus = Literal["draft", "approved", "amended"]

#: A decimal limit sent by the client ("13.5"); judged by the service (422 when malformed).
LabDecimalIn = Annotated[str, Field(pattern=r"^-?[0-9]{1,10}(\.[0-9]{1,4})?$", examples=["13.5"])]

# --- shared references -----------------------------------------------------------------------


class LabUserRefOut(Schema):
    id: int
    username: str
    full_name_ar: str
    full_name_en: str


class LabReasonOut(Schema):
    code: str
    label_ar: str
    label_en: str


class LabPatientOut(Schema):
    id: int
    file_no: str
    full_name_ar: str
    full_name_en: str
    sex: str
    date_of_birth: date | None


class LabTestRefOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str
    sample_type: LabSampleTypeCode
    container: str
    turnaround_minutes: int


class LabSampleOut(Schema):
    id: int
    accession_no: str
    status: LabSampleStatus
    sample_type: LabSampleTypeCode
    collected_at: datetime
    collected_by: LabUserRefOut
    received_at: datetime | None
    received_by: LabUserRefOut | None
    rejection_reason: LabReasonOut | None
    rejection_note: str
    label_printed_at: datetime | None


class LabCenterOut(Schema):
    name_ar: str
    name_en: str
    address: str
    phone: str


# --- work list -------------------------------------------------------------------------------


class LabWorklistParams(Schema):
    status: LabWorklistFilter = "open"
    q: str | None = Field(None, max_length=200)
    page: int = Field(1, ge=1)
    page_size: int = Field(25, ge=1, le=100)


class LabWorklistRowOut(Schema):
    line_id: int
    visit_id: int
    visit_number: str
    patient: LabPatientOut
    test: LabTestRefOut
    stage: LabStage
    ordered_at: datetime
    ordered_by: LabUserRefOut | None
    authorized: bool = Field(description="Performed first under an authorization (not paid).")
    sample: LabSampleOut | None
    critical: bool = Field(description="A value of the current draft or result is critical.")
    due_at: datetime | None = Field(description="Sample receipt plus the test's turnaround.")
    approved_at: datetime | None


class LabStageCountsOut(Schema):
    to_collect: int
    to_receive: int
    to_enter: int
    to_approve: int


class LabWorklistPageOut(Schema):
    items: list[LabWorklistRowOut]
    count: int
    page: int
    page_size: int
    counts: LabStageCountsOut


# --- results ---------------------------------------------------------------------------------


class LabAppliedRangeOut(Schema):
    """The reference range used for this patient (sex and age on the collection date)."""

    low: str | None
    high: str | None
    critical_low: str | None
    critical_high: str | None
    normal_text: str


class LabEntryParameterOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str
    unit: str
    value_type: LabValueTypeCode
    choices: list[str]
    decimals: int
    range: LabAppliedRangeOut | None


class LabValueOut(Schema):
    parameter_id: int
    parameter_code: str
    name_ar: str
    name_en: str
    value: str = Field(description="As shown: a number to the parameter's decimals, or text.")
    unit: str
    reference_low: str | None
    reference_high: str | None
    reference_text: str
    flag: LabFlagCode


class LabVersionOut(Schema):
    id: int
    version_no: int
    status: LabVersionStatus
    amends_version_no: int | None
    amendment_reason: LabReasonOut | None
    amendment_note: str
    comment: str
    entered_by: LabUserRefOut
    entered_at: datetime
    approved_by: LabUserRefOut | None
    approved_at: datetime | None
    superseded_at: datetime | None
    superseded_by: LabUserRefOut | None
    values: list[LabValueOut]
    revision: str | None = Field(description="Draft fingerprint to send with the approval.")


class LabLineOut(Schema):
    id: int
    visit_id: int
    visit_number: str
    fulfilment_status: str
    billing_status: str
    authorized: bool
    ordered_at: datetime
    ordered_by: LabUserRefOut | None
    cancel_reason: LabReasonOut | None
    cancel_note: str
    cancelled_at: datetime | None


class LabCompanionOut(Schema):
    """Another test of the visit waiting for the same kind of sample."""

    line_id: int
    test: LabTestRefOut


class LabResultOut(Schema):
    line: LabLineOut
    patient: LabPatientOut
    test: LabTestRefOut
    stage: LabStage
    sample: LabSampleOut | None
    parameters: list[LabEntryParameterOut]
    versions: list[LabVersionOut]
    companions: list[LabCompanionOut]
    first_approved_at: datetime | None


class LabSampleIn(Schema):
    line_ids: list[int] = Field(..., min_length=1, max_length=20)
    receive: bool = Field(True, description="Drawn in the lab: collected and received at once.")


class LabRejectIn(Schema):
    reason: str = Field(..., min_length=1, max_length=50)
    note: str = Field("", max_length=300)


class LabResultIn(Schema):
    values: dict[str, Annotated[str, Field(max_length=500)]] = Field(default_factory=dict)
    comment: str | None = Field(None, max_length=2000)


class LabApproveIn(Schema):
    revision: str = Field(..., min_length=1, max_length=64)


class LabAmendIn(Schema):
    reason: str = Field(..., min_length=1, max_length=50)
    note: str = Field("", max_length=500)


class LabApproverIn(Schema):
    """A billing supervisor's credentials typed in at the lab bench (ADR 0009)."""

    username: str = Field(..., min_length=1, max_length=150)
    password: str = Field(..., min_length=1, max_length=256)


class LabCancelIn(Schema):
    reason: str = Field(..., min_length=1, max_length=50)
    note: str = Field("", max_length=500)
    approver: LabApproverIn | None = None


class LabLabelOut(Schema):
    sample: LabSampleOut
    patient: LabPatientOut
    visit_number: str
    tests: list[LabTestRefOut]


class LabPrintOut(Schema):
    center: LabCenterOut
    patient: LabPatientOut
    visit_number: str
    test: LabTestRefOut
    sample: LabSampleOut | None
    ordered_by: LabUserRefOut | None
    version: LabVersionOut
    current: bool = Field(description="False when a later amendment replaced this version.")


class LabPrintParams(Schema):
    version_id: int | None = None


# --- approval queue --------------------------------------------------------------------------


class LabApprovalRowOut(Schema):
    line_id: int
    version_id: int
    version_no: int
    amendment: bool
    amendment_reason: LabReasonOut | None
    patient: LabPatientOut
    visit_number: str
    test: LabTestRefOut
    accession_no: str | None
    entered_by: LabUserRefOut
    entered_at: datetime
    critical_count: int
    abnormal_count: int


class LabApprovalPageOut(Schema):
    items: list[LabApprovalRowOut]
    count: int
    page: int
    page_size: int


class LabPageParams(Schema):
    page: int = Field(1, ge=1)
    page_size: int = Field(25, ge=1, le=100)


# --- catalog ---------------------------------------------------------------------------------


class LabServiceOptionOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str


class LabRangeOut(Schema):
    id: int
    sex: LabRangeSexCode
    age_min_days: int
    age_max_days: int | None
    low: str | None
    high: str | None
    critical_low: str | None
    critical_high: str | None
    normal_text: str
    note: str


class LabParameterOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str
    unit: str
    value_type: LabValueTypeCode
    choices: list[str]
    decimals: int
    sort_order: int
    active: bool
    ranges: list[LabRangeOut]


class LabTestOut(Schema):
    id: int
    code: str
    service: LabServiceOptionOut
    name_ar: str
    name_en: str
    sample_type: LabSampleTypeCode
    container: str
    method: str
    turnaround_minutes: int
    instructions_ar: str
    instructions_en: str
    sort_order: int
    active: bool
    parameters: list[LabParameterOut]


class LabTestListItemOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str
    sample_type: LabSampleTypeCode
    turnaround_minutes: int
    active: bool
    parameter_count: int


class LabTestIn(Schema):
    service_id: int
    code: str = Field(..., min_length=1, max_length=30, pattern=r"^[A-Za-z0-9_-]+$")
    sample_type: LabSampleTypeCode
    container: str = Field("", max_length=60)
    method: str = Field("", max_length=100)
    turnaround_minutes: int = Field(60, ge=1, le=60 * 24 * 60)
    instructions_ar: str = Field("", max_length=300)
    instructions_en: str = Field("", max_length=300)
    sort_order: int = Field(0, ge=0, le=100_000)


class LabTestPatch(Schema):
    sample_type: LabSampleTypeCode | None = None
    container: str | None = Field(None, max_length=60)
    method: str | None = Field(None, max_length=100)
    turnaround_minutes: int | None = Field(None, ge=1, le=60 * 24 * 60)
    instructions_ar: str | None = Field(None, max_length=300)
    instructions_en: str | None = Field(None, max_length=300)
    sort_order: int | None = Field(None, ge=0, le=100_000)
    active: bool | None = None


class LabParameterIn(Schema):
    code: str = Field(..., min_length=1, max_length=30, pattern=r"^[A-Za-z0-9_-]+$")
    name_ar: str = Field(..., min_length=1, max_length=150)
    name_en: str = Field(..., min_length=1, max_length=150)
    unit: str = Field("", max_length=30)
    value_type: LabValueTypeCode = "numeric"
    choices: list[Annotated[str, Field(max_length=100)]] = Field(
        default_factory=list, max_length=30
    )
    decimals: int = Field(1, ge=0, le=6)
    sort_order: int = Field(0, ge=0, le=10_000)


class LabParameterPatch(Schema):
    name_ar: str | None = Field(None, min_length=1, max_length=150)
    name_en: str | None = Field(None, min_length=1, max_length=150)
    unit: str | None = Field(None, max_length=30)
    value_type: LabValueTypeCode | None = None
    choices: list[Annotated[str, Field(max_length=100)]] | None = Field(None, max_length=30)
    decimals: int | None = Field(None, ge=0, le=6)
    sort_order: int | None = Field(None, ge=0, le=10_000)
    active: bool | None = None


class LabRangeIn(Schema):
    sex: LabRangeSexCode = "any"
    age_min_days: int = Field(0, ge=0, le=200 * 366)
    age_max_days: int | None = Field(None, ge=1, le=200 * 366)
    low: LabDecimalIn | None = None
    high: LabDecimalIn | None = None
    critical_low: LabDecimalIn | None = None
    critical_high: LabDecimalIn | None = None
    normal_text: str = Field("", max_length=100)
    note: str = Field("", max_length=200)


# --- turnaround report -----------------------------------------------------------------------


class LabTatParams(Schema):
    date_from: date | None = None
    date_to: date | None = None


class LabTatStatsOut(Schema):
    count: int
    mean: int | None
    median: int | None
    p90: int | None
    maximum: int | None
    within_target: int
    within_target_percent: int | None


class LabTatRowOut(Schema):
    test: LabTestRefOut
    stats: LabTatStatsOut
    open_overdue: int


class LabTatOut(Schema):
    date_from: date
    date_to: date
    rows: list[LabTatRowOut]
    total: LabTatStatsOut
