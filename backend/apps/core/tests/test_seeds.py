"""Reference data seeded by migrations: reason codes and the search functions."""

from __future__ import annotations

import importlib

import pytest

from apps.core.models import DoctorProfile, ReasonCategory, ReasonCode
from apps.core.reason_codes import LATER_SEEDS, REASON_CODES, ensure_reason_codes
from apps.core.tests import builders as b

pytestmark = pytest.mark.django_db

REQUIRED_CATEGORIES = {
    "line_cancel",
    "discount",
    "refund",
    "stock_adjust",
    "variance",
    "override",
    "writeoff",
    "visit_cancel",
}


def test_migration_copy_matches_the_reason_list() -> None:
    rows = [
        tuple(row)
        for name in ("0007_seed_reason_codes", *LATER_SEEDS)
        for row in importlib.import_module(f"apps.core.migrations.{name}").REASON_CODES
    ]
    assert rows == [
        (r.category, r.code, r.label_ar, r.label_en, r.requires_note) for r in REASON_CODES
    ]


def test_reason_codes_cover_every_category_with_both_languages() -> None:
    ensure_reason_codes()  # no-op on a fresh database, repairs one a transactional test emptied
    categories = set(ReasonCode.objects.values_list("category", flat=True))
    assert categories >= REQUIRED_CATEGORIES
    assert categories == set(ReasonCategory.values)
    assert all(r.label_ar and r.label_en for r in ReasonCode.objects.all())
    # Every category offers a free-text "other" that demands a note.
    for category in ReasonCategory.values:
        other = ReasonCode.objects.get(category=category, code="OTHER")
        assert other.requires_note
    assert ensure_reason_codes() == 0


def test_seed_keeps_center_edits() -> None:
    ensure_reason_codes()
    ReasonCode.objects.filter(category="discount", code="STAFF").update(label_en="Staff (ours)")
    ensure_reason_codes()
    assert ReasonCode.objects.get(category="discount", code="STAFF").label_en == "Staff (ours)"


def test_doctor_consultation_service() -> None:
    doc = b.doctor()
    svc = b.service(kind="consultation")
    DoctorProfile.objects.filter(pk=doc.pk).update(consultation_service=svc)
    doc.refresh_from_db()
    assert doc.consultation_service == svc
    assert list(svc.consultation_doctors.all()) == [doc]


@pytest.mark.parametrize(
    ("function", "value", "expected"),
    [
        ("hs_normalize_text", "  أحمد   إبراهيم ", "احمد ابراهيم"),
        ("hs_normalize_text", "فاطمة", "فاطمه"),
        ("hs_normalize_text", "مُحَمَّد", "محمد"),
        ("hs_normalize_text", "مـــحمد", "محمد"),
        ("hs_normalize_text", "مصطفى", "مصطفي"),
        ("hs_normalize_text", "آمنة", "امنه"),
        ("hs_normalize_text", "MOHAMED  Ali", "mohamed ali"),
        ("hs_normalize_phone", "+249 91 234 5678", "0912345678"),
        ("hs_normalize_phone", "00249912345678", "0912345678"),
        ("hs_normalize_phone", "٠٩١٢٣٤٥٦٧٨", "0912345678"),
        ("hs_normalize_phone", "0912-345-678", "0912345678"),
        ("hs_normalize_reference", "ft-12 3ab", "FT123AB"),
        ("hs_normalize_reference", "٧٧٧", "777"),
    ],
)
def test_search_normalization_functions(function: str, value: str, expected: str) -> None:
    assert b.sql(f"SELECT {function}(%s)", [value]) == [(expected,)]


def test_pg_trgm_is_installed() -> None:
    assert b.sql("SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'") == [("pg_trgm",)]
