"""Full data export (FEATURES 13.9): a zip of CSV files in open formats, for administrators.

Patients, visits, invoices and their lines, payments, allocations, stock moves, claims and
their lines: every column of every row, one CSV per table (UTF-8 with a byte order mark so
Excel reads Arabic, comma separated, header row of column names), plus ``README.txt``.

* Streamed: rows are read with a server-side cursor in chunks and the zip is written as it
  goes, so neither the server nor the app container holds the whole export in memory or on
  disk (the app's file system is read-only apart from a small /tmp).
* Audited: a :class:`DataExport` row (who, when, which tables) is written before the first
  byte and completed with the row counts and size when the archive ends.
* Safe to open in a spreadsheet: a text cell starting with ``=``, ``+``, ``-``, ``@``, tab or
  carriage return gets a leading apostrophe, so no cell runs as a formula (CSV injection).
  Numbers and dates are written as they are.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from collections.abc import Callable, Iterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pghistory
from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.core.models import User
from apps.core.services import require_permission
from apps.ops.models import DataExport

__all__ = ["EXPORT_TABLES", "begin_export", "csv_cell", "export_filename", "stream_export"]

_CHUNK = 2000
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _models() -> list[tuple[str, type[models.Model]]]:
    from apps.billing.models import Invoice, InvoiceLine
    from apps.claims.models import Claim, ClaimLine
    from apps.patients.models import Patient
    from apps.payments.models import Allocation, Payment
    from apps.pharmacy.models import StockMove
    from apps.visits.models import Visit

    return [
        ("patients", Patient),
        ("visits", Visit),
        ("invoices", Invoice),
        ("invoice_lines", InvoiceLine),
        ("payments", Payment),
        ("allocations", Allocation),
        ("stock_moves", StockMove),
        ("claims", Claim),
        ("claim_lines", ClaimLine),
    ]


#: The files of an export, in order.
EXPORT_TABLES: tuple[str, ...] = (
    "patients",
    "visits",
    "invoices",
    "invoice_lines",
    "payments",
    "allocations",
    "stock_moves",
    "claims",
    "claim_lines",
)


def csv_cell(value: Any) -> str:
    """One value as CSV text; text that a spreadsheet would run as a formula is defused."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | Decimal | float):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict | list):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    else:
        text = str(value)
    return f"'{text}" if text.startswith(_FORMULA_START) else text


class _Sink(io.RawIOBase):
    """A write-only, non-seekable buffer the zip writer fills and the response drains."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[bytes] = []
        self.size = 0

    def writable(self) -> bool:
        return True

    def write(self, data: Any) -> int:
        chunk = bytes(data)
        self._parts.append(chunk)
        self.size += len(chunk)
        return len(chunk)

    def drain(self) -> bytes:
        out = b"".join(self._parts)
        self._parts.clear()
        return out


def export_filename(at: datetime | None = None) -> str:
    stamp = timezone.localtime(at or timezone.now()).strftime("%Y%m%d-%H%M")
    return f"hospital-export-{stamp}.zip"


def begin_export(*, actor: User) -> DataExport:
    """Record the export before it starts (the audit trail shows it even if cut off).

    Raises:
        PermissionRequired: the actor lacks ``ops.export_data``.
    """
    require_permission(actor, "ops.export_data")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="full data export"):
        return DataExport.objects.create(requested_by=actor, tables=list(EXPORT_TABLES))


def _readme(record: DataExport) -> str:
    return (
        "hospital-sys full data export (FEATURES 13.9)\n"
        f"Export number: {record.pk}\n"
        f"Taken at: {timezone.localtime(record.created_at).isoformat()}\n"
        f"Application version: {settings.APP_VERSION}\n\n"
        "One CSV file per table: UTF-8 with a byte order mark, comma separated, the first row\n"
        "holds the column names (database columns; *_id columns refer to the id of a row in\n"
        "another file). Money is in SDG with two decimals. Times are ISO 8601 with offset.\n"
        "Text that starts with = + - @ is prefixed with an apostrophe so that spreadsheets\n"
        "never run it as a formula.\n\n"
        "Files: " + ", ".join(f"{t}.csv" for t in EXPORT_TABLES) + "\n"
    )


def stream_export(
    record: DataExport, *, chunk_rows: int = _CHUNK, on_done: Callable[[], None] | None = None
) -> Iterator[bytes]:
    """The zip archive of ``record`` as a stream of byte chunks; completes ``record``."""
    sink = _Sink()
    counts: dict[str, int] = {}
    with zipfile.ZipFile(sink, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", _readme(record))
        yield sink.drain()
        for name, model in _models():
            fields = [f.attname for f in model._meta.concrete_fields]
            with archive.open(f"{name}.csv", mode="w", force_zip64=True) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
                writer = csv.writer(text, lineterminator="\r\n")
                writer.writerow(fields)
                rows = 0
                queryset = model._default_manager.order_by("pk").values_list(*fields)
                for row in queryset.iterator(chunk_size=chunk_rows):
                    writer.writerow([csv_cell(v) for v in row])
                    rows += 1
                    if rows % chunk_rows == 0:
                        text.flush()
                        yield sink.drain()
                text.flush()
                text.detach()
            counts[name] = rows
            yield sink.drain()
    yield sink.drain()
    with (
        transaction.atomic(),
        pghistory.context(user=record.requested_by_id, reason="full data export finished"),
    ):
        DataExport.objects.filter(pk=record.pk).update(
            row_counts=counts, finished_at=timezone.now(), size_bytes=sink.size
        )
    if on_done is not None:
        on_done()
