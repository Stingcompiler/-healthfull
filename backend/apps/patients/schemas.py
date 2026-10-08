"""Schemas of ``/api/patients`` (ARCHITECTURE 4.11: ``<Thing>In``, ``<Thing>Out``, ``*Patch``).

Money is serialized as decimal strings. Every field here is visible to holders of
``patients.view`` (all clinical and front-desk roles); the balance has its own permission
(``patients.view_balance``) and endpoint.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from ninja import Field, Schema

from api.pagination import PageParams
from apps.patients.services import merge_reason
from domain.money import money

SexCode = Literal["male", "female", "unknown"]
KnownSex = Literal["male", "female"]
MergeReason = Literal["DUPLICATE_REGISTRATION", "EMERGENCY_IDENTIFIED", "SPELLING_VARIANT", "OTHER"]
DuplicateReason = Literal["phone", "national_id", "name_dob"]


def _percent(value: Decimal | None) -> str | None:
    return None if value is None else f"{Decimal(value):.2f}"


# --- shared references ----------------------------------------------------------------------


class PatientRefOut(Schema):
    """A file named by its number (merge history, merged-into links)."""

    id: int
    file_no: str
    full_name_ar: str
    full_name_en: str


class PatientBriefOut(Schema):
    """The patient on a visit, queue token or appointment."""

    id: int
    file_no: str
    full_name_ar: str
    full_name_en: str
    sex: SexCode
    date_of_birth: date | None
    phone: str
    is_incomplete: bool


class UserRefOut(Schema):
    id: int
    name_ar: str
    name_en: str

    @staticmethod
    def resolve_name_ar(obj: Any) -> str:
        return str(obj.display_name_ar)

    @staticmethod
    def resolve_name_en(obj: Any) -> str:
        return str(obj.display_name_en)


class PayerOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str
    kind: str
    requires_card_number: bool


class CoverageBriefOut(Schema):
    """The default coverage shown beside a patient's name."""

    id: int
    payer_id: int
    payer_code: str
    payer_name_ar: str
    payer_name_en: str
    card_number: str

    @staticmethod
    def resolve_payer_code(obj: Any) -> str:
        return str(obj.payer.code)

    @staticmethod
    def resolve_payer_name_ar(obj: Any) -> str:
        return str(obj.payer.name_ar)

    @staticmethod
    def resolve_payer_name_en(obj: Any) -> str:
        return str(obj.payer.name_en)


# --- patient files --------------------------------------------------------------------------


class PatientListOut(Schema):
    """A row of the patient list and of the duplicate warning."""

    id: int
    file_no: str
    full_name_ar: str
    full_name_en: str
    sex: SexCode
    date_of_birth: date | None
    dob_is_estimated: bool
    phone: str
    is_incomplete: bool
    is_active: bool
    merged_into_id: int | None
    created_at: datetime
    coverage: CoverageBriefOut | None = Field(
        None, description="Active default coverage on file; null = self-pay"
    )

    @staticmethod
    def resolve_coverage(obj: Any) -> Any:
        found = getattr(obj, "default_coverages", None)
        if found is None:
            found = list(
                obj.coverages.filter(is_default=True, active=True).select_related("payer")[:1]
            )
        return found[0] if found else None


class PatientOut(PatientListOut):
    """A whole patient file (FEATURES 1.1)."""

    phone_alt: str
    address: str
    national_id: str
    emergency_contact_name: str
    emergency_contact_phone: str
    notes: str
    updated_at: datetime


class AllergyOut(Schema):
    label_ar: str
    label_en: str
    severity: str


class PatientProfileOut(Schema):
    """A file with what reception shows around it."""

    patient: PatientOut
    merged_into: PatientRefOut | None = Field(
        ..., description="The surviving file when this one was merged away"
    )
    allergies: list[AllergyOut] = Field(
        ..., description="Active allergies of the person; empty = none recorded"
    )


class PatientSearchParams(PageParams):
    include_inactive: bool = Field(False, description="Also list merged (inactive) files")
    incomplete: bool = Field(False, description="Only emergency files still to complete")


class PatientIn(Schema):
    """Registration (FEATURES 1.1). Either name is enough; ``age_years`` estimates the birth
    date when it is not known."""

    sex: KnownSex
    full_name_ar: str = Field("", max_length=200)
    full_name_en: str = Field("", max_length=200)
    date_of_birth: date | None = None
    age_years: int | None = Field(None, ge=0, le=130)
    phone: str = Field("", max_length=30)
    phone_alt: str = Field("", max_length=30)
    address: str = Field("", max_length=300)
    national_id: str = Field("", max_length=50)
    emergency_contact_name: str = Field("", max_length=150)
    emergency_contact_phone: str = Field("", max_length=30)
    notes: str = Field("", max_length=2000)
    confirm_not_duplicate: bool = Field(
        False, description="Register even though the duplicate check found similar files"
    )


class EmergencyIn(Schema):
    """Emergency registration with a name (or a placeholder) and sex only (FEATURES 1.2)."""

    name: str = Field(..., min_length=1, max_length=200)
    sex: SexCode
    age_years: int | None = Field(None, ge=0, le=130)
    phone: str = Field("", max_length=30)


class PatientPatch(Schema):
    """Edit demographics; completes an emergency file once sex, birth date and phone exist."""

    sex: SexCode | None = None
    full_name_ar: str | None = Field(None, max_length=200)
    full_name_en: str | None = Field(None, max_length=200)
    date_of_birth: date | None = None
    age_years: int | None = Field(None, ge=0, le=130)
    dob_is_estimated: bool | None = None
    phone: str | None = Field(None, max_length=30)
    phone_alt: str | None = Field(None, max_length=30)
    address: str | None = Field(None, max_length=300)
    national_id: str | None = Field(None, max_length=50)
    emergency_contact_name: str | None = Field(None, max_length=150)
    emergency_contact_phone: str | None = Field(None, max_length=30)
    notes: str | None = Field(None, max_length=2000)


class DuplicateParams(Schema):
    """What the registration form has typed so far (live duplicate warning, FEATURES 1.3)."""

    full_name_ar: str = Field("", max_length=200)
    full_name_en: str = Field("", max_length=200)
    phone: str = Field("", max_length=30)
    phone_alt: str = Field("", max_length=30)
    date_of_birth: date | None = None
    national_id: str = Field("", max_length=50)
    exclude_id: int | None = Field(None, description="The file being edited")


class DuplicateOut(Schema):
    patient: PatientListOut
    reasons: list[DuplicateReason]
    similarity: float = Field(..., description="Name similarity 0-1 (name_dob matches)")


# --- merge ----------------------------------------------------------------------------------


class MergeIn(Schema):
    """Merge ``duplicate_id`` into this (surviving) file (FEATURES 1.4)."""

    duplicate_id: int
    reason_code: MergeReason
    note: str = Field(..., max_length=500)


class MergeOut(Schema):
    id: int
    source: PatientRefOut
    target: PatientRefOut
    reason_code: str = Field(..., description="Merge reason code; empty for older free-text notes")
    note: str
    merged_by: UserRefOut
    merged_at: datetime

    @staticmethod
    def resolve_reason_code(obj: Any) -> str:
        return merge_reason(obj)[0]

    @staticmethod
    def resolve_note(obj: Any) -> str:
        return merge_reason(obj)[1]


# --- coverage on file -----------------------------------------------------------------------


class CoverageOut(Schema):
    id: int
    patient_id: int
    payer: PayerOut
    card_number: str
    member_name: str
    relation: str
    valid_from: date | None
    valid_to: date | None
    patient_percent_override: str | None = Field(
        ..., description="Patient share percent for this member (decimal string); null = payer rule"
    )
    is_default: bool
    active: bool
    created_at: datetime

    @staticmethod
    def resolve_patient_percent_override(obj: Any) -> str | None:
        return _percent(obj.patient_percent_override)


class CoverageIn(Schema):
    payer_id: int
    card_number: str = Field("", max_length=60)
    member_name: str = Field("", max_length=200)
    relation: str = Field("", max_length=30)
    valid_from: date | None = None
    valid_to: date | None = None
    patient_percent_override: Decimal | None = Field(None, max_digits=5, decimal_places=2)
    is_default: bool = True


class CoveragePatch(Schema):
    card_number: str | None = Field(None, max_length=60)
    member_name: str | None = Field(None, max_length=200)
    relation: str | None = Field(None, max_length=30)
    valid_from: date | None = None
    valid_to: date | None = None
    patient_percent_override: Decimal | None = Field(None, max_digits=5, decimal_places=2)
    is_default: bool | None = None


class CoverageListParams(Schema):
    include_inactive: bool = False


# --- balance --------------------------------------------------------------------------------


class OpenInvoiceOut(Schema):
    invoice_id: int
    number: str
    outstanding: str

    @staticmethod
    def resolve_outstanding(obj: Any) -> str:
        return str(money(obj.outstanding))


class BalanceOut(Schema):
    """The person's money position (FEATURES 1.5); decimal strings in SDG."""

    credit: str = Field(..., description="Patient credit (negative: the patient owes it)")
    spendable: str = Field(..., description="Credit that may be spent or refunded now")
    pending: str = Field(..., description="Unallocated transfer money awaiting verification")
    outstanding: str = Field(..., description="Patient share still owed on approved invoices")
    net: str = Field(..., description="outstanding - credit; positive: the patient owes")
    invoices: list[OpenInvoiceOut]

    @staticmethod
    def resolve_credit(obj: Any) -> str:
        return str(money(obj.credit))

    @staticmethod
    def resolve_spendable(obj: Any) -> str:
        return str(money(obj.spendable))

    @staticmethod
    def resolve_pending(obj: Any) -> str:
        return str(money(obj.pending))

    @staticmethod
    def resolve_outstanding(obj: Any) -> str:
        return str(money(obj.outstanding))

    @staticmethod
    def resolve_net(obj: Any) -> str:
        return str(money(obj.net))
