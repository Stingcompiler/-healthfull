"""Shared schema building blocks for every app (ARCHITECTURE 4.3, 4.9).

* Field factories: money (``DecimalField(14, 2)``), quantities (``DecimalField(14, 3)``) and
  unit costs (``DecimalField(16, 4)``). Never floats.
* SQL functions for search normalization (installed by ``core.0005``) and the matching
  ``Func`` expressions, so generated columns, indexes and queries normalize the same way.
* Trigger factories for the immutability rules: append-only tables, rows frozen by a
  status, and "no new money rows on a closed shift". Every trigger raises
  ``<CODE>: <message>`` so a violation is recognizable in logs and tests.
* ``choice_check`` builds a ``CheckConstraint`` that keeps an enum column inside its
  ``TextChoices``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pghistory
import pgtrigger
from django.db import models

ZERO = Decimal("0.00")

# --- Field factories ---------------------------------------------------------------------


def money_field(**kwargs: Any) -> models.DecimalField[Any, Any]:
    """Money in SDG: ``Decimal`` with 2 places (ARCHITECTURE 4.3)."""
    kwargs.setdefault("max_digits", 14)
    kwargs.setdefault("decimal_places", 2)
    return models.DecimalField(**kwargs)


def quantity_field(**kwargs: Any) -> models.DecimalField[Any, Any]:
    """Quantities (service units, stock in base units): ``Decimal`` with 3 places."""
    kwargs.setdefault("max_digits", 14)
    kwargs.setdefault("decimal_places", 3)
    return models.DecimalField(**kwargs)


def cost_field(**kwargs: Any) -> models.DecimalField[Any, Any]:
    """Unit cost per base unit (stock valuation only, never invoiced): 4 places."""
    kwargs.setdefault("max_digits", 16)
    kwargs.setdefault("decimal_places", 4)
    return models.DecimalField(**kwargs)


def percent_field(**kwargs: Any) -> models.DecimalField[Any, Any]:
    """A percentage 0-100 with 2 places."""
    kwargs.setdefault("max_digits", 5)
    kwargs.setdefault("decimal_places", 2)
    return models.DecimalField(**kwargs)


# --- Constraints -------------------------------------------------------------------------


def choice_check(
    field: str, choices: type[models.TextChoices], name: str
) -> models.CheckConstraint:
    """``CHECK (field IN (...))`` for a ``TextChoices`` column."""
    return models.CheckConstraint(
        condition=models.Q(**{f"{field}__in": list(choices.values)}), name=name
    )


# --- History -----------------------------------------------------------------------------


def track_history(*, exclude: list[str] | None = None) -> Any:
    """``pghistory.track`` with insert, update and delete snapshots (mutable models)."""
    kwargs: dict[str, Any] = {}
    if exclude:
        kwargs["exclude"] = exclude
    return pghistory.track(
        pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent(), **kwargs
    )


# --- Search normalization (SQL functions from migration core.0005) ----------------------


class NormalizeText(models.Func):
    """``hs_normalize_text(text)``: lower case, Arabic letter variants folded, diacritics and
    tatweel removed, whitespace collapsed. IMMUTABLE, usable in indexes and generated columns.
    """

    function = "hs_normalize_text"
    output_field = models.TextField()


class NormalizePhone(models.Func):
    """``hs_normalize_phone(text)``: digits only (Arabic-Indic digits mapped to 0-9), with a
    Sudan country prefix (``+249`` / ``00249``) folded to the national ``0`` prefix.
    """

    function = "hs_normalize_phone"
    output_field = models.TextField()


class NormalizeReference(models.Func):
    """``hs_normalize_reference(text)``: upper-case letters and digits only, so ``ft-12 3``
    and ``FT123`` are the same bank reference.
    """

    function = "hs_normalize_reference"
    output_field = models.TextField()


# --- Triggers ----------------------------------------------------------------------------


def _raise(code: str, message: str) -> str:
    return (
        f"RAISE EXCEPTION '{code}: {message} (table %, operation %)', TG_TABLE_NAME, TG_OP; "
        "RETURN NULL;"
    )


def append_only(name: str = "append_only") -> pgtrigger.Trigger:
    """Rows can be inserted, never updated or deleted (ledger-style tables)."""
    return pgtrigger.Trigger(
        name=name,
        when=pgtrigger.Before,
        operation=pgtrigger.Update | pgtrigger.Delete,
        func=_raise("APPEND_ONLY", "rows are append-only"),
    )


def protect_when(
    name: str,
    *,
    code: str,
    message: str,
    condition: pgtrigger.Condition | None = None,
    operation: pgtrigger.Operation | None = None,
) -> pgtrigger.Trigger:
    """Refuse UPDATE/DELETE (or ``operation``) of rows matching ``condition`` (all rows when
    ``condition`` is None)."""
    return pgtrigger.Trigger(
        name=name,
        when=pgtrigger.Before,
        operation=operation or (pgtrigger.Update | pgtrigger.Delete),
        condition=condition,
        func=_raise(code, message),
    )


def shift_must_be_open(name: str = "shift_must_be_open", column: str = "shift_id") -> Any:
    """Refuse rows that reference a shift that is not open (invariant 3).

    Applies on INSERT and on UPDATE that changes the shift. Later effects of a closed shift
    are posted to the acting user's current open shift instead (ARCHITECTURE 4.6).
    """
    return pgtrigger.Trigger(
        name=name,
        when=pgtrigger.Before,
        operation=pgtrigger.Insert | pgtrigger.Update,
        # Trigger DDL built at import time from code constants, never from user input.
        func=f"""
            IF NEW.{column} IS NOT NULL
               AND (TG_OP = 'INSERT' OR NEW.{column} IS DISTINCT FROM OLD.{column})
               AND NOT EXISTS (
                   SELECT 1 FROM payments_shift s WHERE s.id = NEW.{column} AND s.status = 'open'
               ) THEN
                RAISE EXCEPTION 'SHIFT_NOT_OPEN: shift % is not open (table %)',
                    NEW.{column}, TG_TABLE_NAME;
            END IF;
            RETURN NEW;
        """,  # noqa: S608
    )


def parent_must_be_editable(
    name: str,
    *,
    code: str,
    parent_table: str,
    fk_column: str,
    editable_condition: str,
    operation: pgtrigger.Operation | None = None,
) -> pgtrigger.Trigger:
    """Refuse INSERT/UPDATE/DELETE (or ``operation``) of child rows whose parent is locked.

    ``editable_condition`` is SQL over alias ``p`` (the parent row), e.g. ``p.status = 'draft'``.
    A row whose parent no longer exists (deleted earlier in a cascade) is not checked.
    """
    return pgtrigger.Trigger(
        name=name,
        when=pgtrigger.Before,
        operation=operation or (pgtrigger.Insert | pgtrigger.Update | pgtrigger.Delete),
        # Trigger DDL built at import time from code constants, never from user input.
        func=f"""
            IF TG_OP IN ('UPDATE', 'DELETE') AND NOT EXISTS (
                SELECT 1 FROM {parent_table} p WHERE p.id = OLD.{fk_column} AND {editable_condition}
            ) AND EXISTS (SELECT 1 FROM {parent_table} p WHERE p.id = OLD.{fk_column}) THEN
                RAISE EXCEPTION '{code}: parent % of % row is locked', OLD.{fk_column},
                    TG_TABLE_NAME;
            END IF;
            IF TG_OP IN ('INSERT', 'UPDATE') AND NOT EXISTS (
                SELECT 1 FROM {parent_table} p WHERE p.id = NEW.{fk_column} AND {editable_condition}
            ) THEN
                RAISE EXCEPTION '{code}: parent % of % row is locked', NEW.{fk_column},
                    TG_TABLE_NAME;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        """,  # noqa: S608
    )
