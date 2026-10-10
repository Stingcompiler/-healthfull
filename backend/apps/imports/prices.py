"""Price list items from a sheet into a version that has not started (FEATURES 5.2; ADR 0014).

The upload names the price list and the version's start date, which must be after today:
an effective version never changes (invariant 6), and an import never creates one that
starts today. Confirm goes through the catalog services only:

* a version of that list already starting on that date (planned, not started) gets the
  imported prices (``catalog.set_prices``, which refuses a version that has started);
* otherwise a new version copies the one effective on that date and applies the imported
  prices (``catalog.derive_version``: dated versions, one per date, never backdated).

All rows go in together: a refused version leaves nothing changed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from apps.catalog import services as catalog
from apps.catalog.models import PriceList, PriceListVersion, Service
from apps.core.models import User
from apps.imports.models import ImportJob, ImportRow, RowStatus
from apps.imports.rows import RowDraft
from domain import price_import as dpi
from domain.errors import DomainError

__all__ = ["COLUMNS", "DUPLICATE_HINTS", "clean_options", "confirm", "parse"]

COLUMNS = dpi.COLUMNS
DUPLICATE_HINTS = frozenset({"in_file"})


def clean_options(options: Mapping[str, Any], *, today: date) -> dict[str, Any]:
    """``price_list`` (code) and ``effective_from`` (ISO date after today), both required.

    Raises:
        DomainError: ``IMPORT_OPTION_REQUIRED``, ``IMPORT_OPTION_INVALID``,
            ``PRICE_LIST_UNKNOWN``, ``PRICE_LIST_INACTIVE``, ``PRICE_VERSION_BACKDATED``.
    """
    code = str(options.get("price_list") or "").strip().upper()
    raw = str(options.get("effective_from") or "").strip()
    for name, value in (("price_list", code), ("effective_from", raw)):
        if not value:
            raise DomainError("IMPORT_OPTION_REQUIRED", "This import needs an option", option=name)
    try:
        effective = date.fromisoformat(raw)
    except ValueError:
        raise DomainError(
            "IMPORT_OPTION_INVALID", "The start date is not a date", option="effective_from"
        ) from None
    plist = PriceList.objects.filter(code=code).first()
    if plist is None:
        raise DomainError("PRICE_LIST_UNKNOWN", "Unknown price list", price_list=code)
    if not plist.active:
        raise DomainError("PRICE_LIST_INACTIVE", "The price list is inactive")
    if effective <= today:
        raise DomainError(
            "PRICE_VERSION_BACKDATED",
            "Imported prices go into a version that starts after today",
            effective_from=effective.isoformat(),
        )
    return {"price_list": code, "effective_from": effective.isoformat()}


def _target(options: Mapping[str, Any]) -> tuple[PriceList, date, PriceListVersion | None]:
    plist = PriceList.objects.get(code=options["price_list"])
    effective = date.fromisoformat(str(options["effective_from"]))
    planned = PriceListVersion.objects.filter(price_list=plist, effective_from=effective).first()
    return plist, effective, planned


def _base_prices(options: Mapping[str, Any]) -> dict[int, Decimal]:
    plist, effective, planned = _target(options)
    if planned is not None:
        return catalog.version_prices(planned)
    try:
        return catalog.version_prices(catalog.effective_version(plist, effective))
    except DomainError as exc:
        if exc.code != "NO_EFFECTIVE_PRICE_LIST":
            raise
        return {}


def parse(
    rows: Sequence[tuple[int, Mapping[str, Any]]], *, options: Mapping[str, Any], today: date
) -> list[RowDraft]:
    codes = {
        str(v).strip().upper()
        for _, cells in rows
        if (v := cells.get("service_code")) not in (None, "")
    }
    services = {
        code.upper(): pk
        for pk, code in Service.objects.filter(code__in=codes).values_list("id", "code")
    }
    parsed = dpi.parse_rows(rows, services=services, current=_base_prices(options))
    return [
        RowDraft(row_no=r.row_no, data=r.data, errors=r.errors, warnings=r.warnings) for r in parsed
    ]


def confirm(
    job: ImportJob, rows: Sequence[ImportRow], *, actor: User, today: date
) -> dict[str, Any]:
    """Put the prices of ``rows`` (in sheet order, a later row wins) into the target version.

    Raises:
        DomainError: from the catalog services (``PRICE_VERSION_LOCKED``, ``INVALID_PRICE``,
            ``SERVICE_UNKNOWN``, ``PRICE_VERSION_BACKDATED``, ...); nothing is changed.
    """
    plist, effective, planned = _target(job.options)
    if effective <= today:
        raise DomainError(
            "PRICE_VERSION_BACKDATED",
            "Imported prices go into a version that starts after today",
            effective_from=effective.isoformat(),
        )
    changes: dict[int, Decimal | None] = {}
    for row in rows:
        changes[int(row.data["service_id"])] = Decimal(str(row.data["price"]))
    if planned is not None:
        version = catalog.set_prices(planned, changes, actor=actor, today=today)
    else:
        version = catalog.derive_version(
            plist,
            effective_from=effective,
            actor=actor,
            changes=changes,
            note=f"Excel import {job.pk}",
            today=today,
        )
    for row in rows:
        row.status = RowStatus.IMPORTED
        row.result_id = version.pk
        row.save(update_fields=["status", "result_id"])
    return {
        "version_id": version.pk,
        "price_list": plist.code,
        "effective_from": effective.isoformat(),
    }
