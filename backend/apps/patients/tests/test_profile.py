"""Patient services added for the registration screens (wave a): paged search, profile,
coverage edits, merge with a reason code, merge history and the balance view."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from apps.clinical.models import Allergy
from apps.core.tests import builders as b
from apps.patients import services as ps
from domain.errors import DomainError

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 7)


@pytest.fixture
def clerk(make_user):
    return make_user(roles=["receptionist"])


@pytest.fixture
def supervisor(make_user):
    return make_user(roles=["manager"])


def _register(clerk, **kw):
    kw.setdefault("sex", "male")
    return ps.register_patient(ps.PatientData(**kw), actor=clerk, confirm_not_duplicate=True)


# --- paged search ---------------------------------------------------------------------------


def test_search_queryset_pages_and_filters(clerk) -> None:
    ahmed = _register(clerk, full_name_ar="أحمد إبراهيم", phone="0912000001")
    fatima = _register(clerk, full_name_ar="فاطمة مصطفى", sex="female", phone="0912000002")
    emergency = ps.register_emergency(name="مجهول طوارئ", sex="unknown", actor=clerk)

    # No query: the newest files first.
    assert list(ps.search(""))[:3] == [emergency, fatima, ahmed]
    assert list(ps.search("", incomplete_only=True)) == [emergency]
    assert list(ps.search("احمد ابراهيم")) == [ahmed]
    assert list(ps.search(fatima.file_no)) == [fatima]
    assert list(ps.search("0912000002")) == [fatima]
    # The default coverage rides along without a query per row.
    insurer = b.payer(requires_card_number=False)
    cov = ps.add_coverage(ahmed, payer=insurer, actor=clerk)
    found = list(ps.search("احمد"))
    assert found == [ahmed]
    assert found[0].default_coverages == [cov]  # type: ignore[attr-defined]


def test_search_skips_merged_files_unless_asked(clerk, supervisor) -> None:
    keep = _register(clerk, full_name_ar="سلمى عوض")
    dup = _register(clerk, full_name_ar="سلمي عوض")
    ps.merge_patients(dup, keep, actor=supervisor, reason_note="same person")
    assert list(ps.search("سلمى عوض")) == [keep]
    assert set(ps.search("سلمى عوض", include_inactive=True)) == {keep, dup}


# --- profile --------------------------------------------------------------------------------


def test_profile_names_allergies_and_survivor(clerk, supervisor) -> None:
    keep = _register(clerk, full_name_ar="منى حسن", sex="female")
    dup = _register(clerk, full_name_ar="منى حسن", sex="female")
    Allergy.objects.create(
        patient=dup, allergen_type="food", substance="Peanuts", severity="severe", recorded_by=clerk
    )
    ps.merge_patients(dup, keep, actor=supervisor, reason_note="same person")

    profile = ps.profile(keep)
    assert profile.patient == keep
    assert profile.merged_into is None
    assert [(a.label_ar, a.label_en, a.severity) for a in profile.allergies] == [
        ("Peanuts", "Peanuts", "severe")
    ]
    merged = ps.profile(dup)
    assert merged.merged_into == keep
    # A merged file shows the person's allergies (they moved to the surviving file).
    assert [a.label_en for a in merged.allergies] == ["Peanuts"]


def test_profile_without_allergies_says_not_recorded(clerk) -> None:
    p = _register(clerk, full_name_en="No Record")
    assert ps.profile(p).allergies == []


# --- coverage edits -------------------------------------------------------------------------


def test_update_coverage(clerk) -> None:
    p = _register(clerk, full_name_en="Covered")
    insurer = b.payer()
    first = ps.add_coverage(p, payer=insurer, actor=clerk, card_number="C-1")
    second = ps.add_coverage(p, payer=b.payer(requires_card_number=False), actor=clerk)

    updated = ps.update_coverage(
        first,
        actor=clerk,
        card_number=" C-2 ",
        valid_to=TODAY + timedelta(days=365),
        patient_percent_override=Decimal("15.00"),
        is_default=True,
    )
    assert updated.card_number == "C-2"
    assert updated.patient_percent_override == Decimal("15.00")
    assert updated.is_default
    second.refresh_from_db()
    assert not second.is_default
    with pytest.raises(DomainError) as exc:
        ps.update_coverage(first, actor=clerk, card_number="")
    assert exc.value.code == "CARD_NUMBER_REQUIRED"
    with pytest.raises(DomainError) as exc:
        ps.update_coverage(first, actor=clerk, valid_from=TODAY, valid_to=TODAY - timedelta(1))
    assert exc.value.code == "INVALID_DATE_RANGE"
    with pytest.raises(DomainError) as exc:
        ps.update_coverage(first, actor=clerk, patient_percent_override=Decimal("-1"))
    assert exc.value.code == "INVALID_PERCENT"
    with pytest.raises(DomainError) as exc:
        ps.update_coverage(first, actor=clerk, payer=insurer)
    assert exc.value.code == "FIELD_NOT_EDITABLE"
    ended = ps.end_coverage(first, actor=clerk)
    with pytest.raises(DomainError) as exc:
        ps.update_coverage(ended, actor=clerk, card_number="C-3")
    assert exc.value.code == "COVERAGE_ENDED"


def test_coverages_of_a_file(clerk) -> None:
    p = _register(clerk, full_name_en="Two Payers")
    old = ps.add_coverage(p, payer=b.payer(requires_card_number=False), actor=clerk)
    new = ps.add_coverage(p, payer=b.payer(requires_card_number=False), actor=clerk)
    ps.end_coverage(old, actor=clerk)
    assert ps.coverages(p) == [new]
    assert ps.coverages(p, include_inactive=True) == [new, old]


def test_active_payers_lists_only_active(clerk) -> None:
    on = b.payer()
    off = b.payer(active=False)
    payers = list(ps.active_payers())
    assert on in payers
    assert off not in payers


# --- merge with a reason code ---------------------------------------------------------------


def test_merge_into_records_code_and_note(clerk, supervisor) -> None:
    keep = _register(clerk, full_name_ar="عمر الفاتح")
    dup = _register(clerk, full_name_ar="عمر الفاتح")
    with pytest.raises(PermissionDenied):
        ps.merge_into(
            keep, duplicate=dup, actor=clerk, reason_code="DUPLICATE_REGISTRATION", note="x"
        )
    with pytest.raises(DomainError) as exc:
        ps.merge_into(keep, duplicate=dup, actor=supervisor, reason_code="BOGUS", note="x")
    assert exc.value.code == "REASON_UNKNOWN"
    with pytest.raises(DomainError) as exc:
        ps.merge_into(
            keep, duplicate=dup, actor=supervisor, reason_code="DUPLICATE_REGISTRATION", note=" "
        )
    assert exc.value.code == "REASON_REQUIRED"
    merge = ps.merge_into(
        keep,
        duplicate=dup,
        actor=supervisor,
        reason_code="DUPLICATE_REGISTRATION",
        note="registered twice at reception",
    )
    assert merge.source == dup
    assert merge.target == keep
    assert merge.reason_note == "DUPLICATE_REGISTRATION: registered twice at reception"
    assert ps.merge_reason(merge) == ("DUPLICATE_REGISTRATION", "registered twice at reception")
    assert ps.merges(keep) == [merge]
    assert ps.merges(dup) == [merge]


def test_merge_reason_of_a_free_text_note() -> None:
    class Row:
        reason_note = "same person"

    assert ps.merge_reason(Row()) == ("", "same person")  # type: ignore[arg-type]


# --- balance --------------------------------------------------------------------------------


def test_balance_of_a_new_file_is_zero(clerk) -> None:
    p = _register(clerk, full_name_en="Zero")
    bal = ps.balance(p)
    assert (bal.credit, bal.spendable, bal.pending, bal.outstanding, bal.net) == (
        Decimal(0),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        Decimal(0),
    )
    assert bal.invoices == ()
