"""Schemas of ``/api/imports`` (ARCHITECTURE 4.11): import jobs of every kind (patients,
items with opening stock, prices), their rows and the templates."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from ninja import Field, Schema

from api.pagination import PageParams
from apps.patients.schemas import UserRefOut

JobStatusCode = Literal["uploaded", "validated", "confirmed", "failed", "cancelled"]
RowStatusCode = Literal["valid", "warning", "error", "duplicate", "imported", "skipped"]
RowFilter = Literal["problems", "valid", "warning", "error", "duplicate", "imported", "skipped"]
ImportKindCode = Literal["patients", "items", "prices"]


class ImportJobOut(Schema):
    id: int
    kind: str
    status: JobStatusCode
    original_filename: str
    total_rows: int
    valid_rows: int
    error_rows: int
    duplicate_rows: int
    imported_rows: int
    skipped_rows: int
    created_at: datetime
    uploaded_by: UserRefOut
    confirmed_at: datetime | None
    confirmed_by: UserRefOut | None
    options: dict[str, Any] = Field(
        ..., description="items: store; prices: price_list and effective_from"
    )
    summary: dict[str, Any] = Field(
        ...,
        description=(
            "After confirm: skipped, include_duplicates; items: receipts (goods receipt "
            "numbers of the opening stock); prices: version_id, price_list, effective_from"
        ),
    )

    @staticmethod
    def resolve_skipped_rows(obj: Any) -> int:
        return int((obj.summary or {}).get("skipped", 0))


class ImportPatientDataOut(Schema):
    """A row as read from the sheet (empty strings for empty cells)."""

    full_name_ar: str = ""
    full_name_en: str = ""
    sex: str = ""
    date_of_birth: str | None = None
    age_years: int | None = None
    phone: str = ""
    phone_alt: str = ""
    address: str = ""
    national_id: str = ""
    emergency_contact_name: str = ""
    emergency_contact_phone: str = ""
    notes: str = ""


class RowErrorOut(Schema):
    code: str = Field(..., description="An errors-namespace code (NAME_REQUIRED, INVALID_SEX...)")
    field: str


class RowHintOut(Schema):
    """A possible duplicate: an existing file (phone, national_id, name_dob) or an earlier row."""

    code: Literal["phone", "national_id", "name_dob", "in_file"]
    patient_id: int | None = None
    file_no: str | None = None
    name: str | None = None
    row_no: int | None = None


class ImportRowOut(Schema):
    row_no: int = Field(..., description="The row number in the sheet (1 = header)")
    status: RowStatusCode
    data: ImportPatientDataOut
    errors: list[RowErrorOut]
    warnings: list[RowHintOut]
    result_id: int | None = Field(..., description="The patient file created from the row")


class ImportJobRowOut(Schema):
    """A row of any import kind: ``data`` holds the parsed columns of that kind."""

    row_no: int = Field(..., description="The row number in the sheet (1 = header)")
    status: RowStatusCode
    data: dict[str, Any]
    errors: list[RowErrorOut]
    warnings: list[dict[str, Any]] = Field(
        ...,
        description=(
            "Hints with a code: patients phone, national_id, name_dob, in_file; items "
            "item_exists, batch_exists, stock_exists, in_file; prices unchanged, in_file"
        ),
    )
    result_id: int | None = Field(
        ..., description="patients: the file; items: the stock item; prices: the version"
    )


class JobListParams(PageParams):
    kind: ImportKindCode | None = None


class RowParams(PageParams):
    status: RowFilter | None = Field(None, description="problems = errors and duplicates")


class ConfirmIn(Schema):
    include_duplicates: bool = Field(
        False, description="Also register the rows flagged as possible duplicates"
    )


class TemplateParams(Schema):
    language: Literal["ar", "en"] = "en"
