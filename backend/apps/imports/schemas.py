"""Schemas of ``/api/imports`` (ARCHITECTURE 4.11). Patient import preview and result."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from ninja import Field, Schema

from api.pagination import PageParams
from apps.patients.schemas import UserRefOut

JobStatusCode = Literal["uploaded", "validated", "confirmed", "failed", "cancelled"]
RowStatusCode = Literal["valid", "warning", "error", "duplicate", "imported", "skipped"]
RowFilter = Literal["problems", "valid", "error", "duplicate", "imported", "skipped"]


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


class RowParams(PageParams):
    status: RowFilter | None = Field(None, description="problems = errors and duplicates")


class ConfirmIn(Schema):
    include_duplicates: bool = Field(
        False, description="Also register the rows flagged as possible duplicates"
    )


class TemplateParams(Schema):
    language: Literal["ar", "en"] = "en"
