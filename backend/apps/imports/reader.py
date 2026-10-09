"""Reading an uploaded sheet safely (FEATURES 1.8, 8.13; ADR 0014).

* Only ``.xlsx`` (an Office Open XML zip) and ``.csv`` are read; the content must look like
  its extension says (zip signature, no NUL bytes in text), whatever the browser claimed.
* An ``.xlsx`` is a zip: its unpacked size is checked before parsing, so a small upload that
  unpacks to gigabytes (a decompression bomb) is refused.
* Formulas are never evaluated: the workbook is opened without cached values and a formula
  cell becomes :data:`domain.sheet.FORMULA`, which the row parsers refuse.
* Only the first sheet is read, at most ``MAX_ROWS`` data rows.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from domain import sheet
from domain.errors import DomainError
from domain.sheet import Column

__all__ = [
    "MAX_FILE_BYTES",
    "MAX_ROWS",
    "MAX_UNPACKED_BYTES",
    "check_size",
    "is_blank",
    "read_sheet",
    "table",
]

#: Largest accepted upload (a 2,000-row sheet is far below this).
MAX_FILE_BYTES = 5 * 1024 * 1024
#: Largest unpacked size of an .xlsx (all its parts together).
MAX_UNPACKED_BYTES = 60 * 1024 * 1024
#: Rows per import; larger lists are split into several files.
MAX_ROWS = 2000

XLSX_SUFFIXES = (".xlsx", ".xlsm")
CSV_SUFFIXES = (".csv",)
_ZIP_MAGIC = b"PK\x03\x04"


def check_size(content: bytes, limit: int | None = None) -> None:
    most = MAX_FILE_BYTES if limit is None else limit
    if len(content) > most:
        raise DomainError(
            "IMPORT_FILE_TOO_LARGE", "The file is too large", limit_mb=max(1, most // 2**20)
        )


def _invalid(message: str = "The file is not a readable Excel file") -> DomainError:
    return DomainError("IMPORT_FILE_INVALID", message)


def _check_zip(content: bytes) -> None:
    if not content.startswith(_ZIP_MAGIC):
        raise _invalid()
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            unpacked = sum(info.file_size for info in archive.infolist())
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise _invalid() from exc
    if unpacked > MAX_UNPACKED_BYTES:
        raise DomainError(
            "IMPORT_FILE_TOO_LARGE",
            "The file unpacks to too much data",
            limit_mb=MAX_UNPACKED_BYTES // 2**20,
        )


def _xlsx_rows(content: bytes) -> Iterator[list[Any]]:
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    _check_zip(content)
    try:
        # data_only=False: formulas come back as formulas (never their cached results).
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise _invalid() from exc
    try:
        if not book.worksheets:
            raise _invalid()
        for cells in book.worksheets[0].iter_rows():
            yield [
                sheet.FORMULA if getattr(c, "data_type", None) == "f" else c.value for c in cells
            ]
    except (KeyError, OSError, ValueError, zipfile.BadZipFile) as exc:
        raise _invalid() from exc
    finally:
        book.close()


def _csv_rows(content: bytes) -> Iterator[list[Any]]:
    if b"\x00" in content:
        raise _invalid("The file is not readable text")
    for encoding in ("utf-8-sig", "cp1256"):
        try:
            text = content.decode(encoding)
        except UnicodeDecodeError:
            continue
        try:
            yield from (list(r) for r in csv.reader(io.StringIO(text)))
        except csv.Error as exc:
            raise _invalid("The file is not readable text") from exc
        return
    raise _invalid("The file is not readable text")  # pragma: no cover - cp1256 reads any byte


def read_sheet(filename: str, content: bytes) -> Iterator[tuple[int, list[Any]]]:
    """``(sheet row number, cells)`` of the first sheet, 1-based like Excel."""
    suffix = Path(filename).suffix.lower()
    if suffix in XLSX_SUFFIXES:
        rows: Iterator[list[Any]] = _xlsx_rows(content)
    elif suffix in CSV_SUFFIXES:
        rows = _csv_rows(content)
    else:
        raise DomainError(
            "IMPORT_FILE_INVALID", "Upload an Excel (.xlsx) or CSV file", filename=filename[:80]
        )
    yield from enumerate(rows, start=1)


def is_blank(cells: Sequence[Any]) -> bool:
    return all(c is None or (c is not sheet.FORMULA and str(c).strip() == "") for c in cells)


def table(
    filename: str, content: bytes, columns: Sequence[Column]
) -> list[tuple[int, dict[str, Any]]]:
    """The data rows of a sheet as ``(row number, field key to cell)`` under its header row.

    Raises:
        DomainError: ``IMPORT_FILE_INVALID``, ``IMPORT_FILE_TOO_LARGE``,
            ``IMPORT_HEADERS_MISSING`` (``details.missing``), ``IMPORT_NO_ROWS``,
            ``IMPORT_TOO_MANY_ROWS`` (``details.limit``).
    """
    check_size(content)
    header: dict[int, str] | None = None
    rows: list[tuple[int, dict[str, Any]]] = []
    for number, cells in read_sheet(filename, content):
        if is_blank(cells):
            continue
        if header is None:
            header = sheet.match_headers(columns, cells)
            missing = sheet.missing_headers(columns, header)
            if missing:
                raise DomainError(
                    "IMPORT_HEADERS_MISSING", "Required columns are missing", missing=missing
                )
            continue
        rows.append((number, {k: cells[p] if p < len(cells) else None for p, k in header.items()}))
        if len(rows) > MAX_ROWS:
            raise DomainError("IMPORT_TOO_MANY_ROWS", "Too many rows in one file", limit=MAX_ROWS)
    if not rows:
        raise DomainError("IMPORT_NO_ROWS", "The file has no data rows")
    return rows
