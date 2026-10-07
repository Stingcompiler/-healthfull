"""Patient services: registration, duplicates, Arabic-tolerant search, merge, coverage."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.clinical.models import Allergy
from apps.core.tests import builders as b
from apps.patients import services as ps
from apps.patients.models import Patient, PatientCoverage, PatientMerge
from apps.visits.models import Appointment
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
    confirm = kw.pop("confirm", False)
    return ps.register_patient(
        ps.PatientData(**kw), actor=clerk, confirm_not_duplicate=confirm, today=TODAY
    )


# --- normalization --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "folded"),
    [
        ("أحمد", "احمد"),
        ("إبراهيم", "ابراهيم"),
        ("آمنة", "امنه"),
        ("فاطمة", "فاطمه"),
        ("مصطفى", "مصطفي"),
        ("عــلـي", "علي"),
        ("مُحَمَّد", "محمد"),
        ("  Ahmed   ALI ", "ahmed ali"),
    ],
)
def test_normalize_text_folds_arabic_variants(raw: str, folded: str) -> None:
    assert ps.normalize_text(raw) == folded


@pytest.mark.parametrize(
    ("raw", "folded"),
    [
        ("+249 912 345 678", "0912345678"),
        ("00249912345678", "0912345678"),
        ("٠٩١٢٣٤٥٦٧٨", "0912345678"),
        ("0912-345-678", "0912345678"),
    ],
)
def test_normalize_phone(raw: str, folded: str) -> None:
    assert ps.normalize_phone(raw) == folded


# --- registration ---------------------------------------------------------------------------


def test_register_assigns_file_number_and_records_actor(clerk) -> None:
    p = _register(
        clerk, full_name_ar="أحمد علي", phone="0912345678", date_of_birth=date(1990, 1, 1)
    )
    assert p.file_no.startswith(f"PT-{timezone.localdate().year}-")
    assert p.created_by == clerk
    assert not p.is_incomplete
    assert p.events.first().pgh_context.metadata["user"] == clerk.pk
    q = _register(clerk, full_name_en="Sara Omer", sex="female")
    assert q.file_no != p.file_no


def test_register_estimates_birth_date_from_age(clerk) -> None:
    p = _register(clerk, full_name_ar="عمر", age_years=30)
    assert p.date_of_birth == date(1996, 10, 7)
    assert p.dob_is_estimated


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"full_name_ar": " ", "full_name_en": ""}, "NAME_REQUIRED"),
        ({"full_name_ar": "علي", "sex": "unknown"}, "INVALID_SEX"),
        (
            {"full_name_ar": "علي", "date_of_birth": TODAY + timedelta(days=1)},
            "INVALID_DATE_OF_BIRTH",
        ),
        ({"full_name_ar": "علي", "age_years": 200}, "INVALID_AGE"),
    ],
)
def test_register_validation(clerk, kwargs, code) -> None:
    with pytest.raises(DomainError) as exc:
        _register(clerk, **kwargs)
    assert exc.value.code == code


def test_duplicate_warning_on_same_phone(clerk) -> None:
    first = _register(clerk, full_name_ar="محمد أحمد", phone="+249912000111")
    with pytest.raises(DomainError) as exc:
        _register(clerk, full_name_ar="شخص آخر", phone="0912000111")
    assert exc.value.code == "DUPLICATE_PATIENT"
    assert exc.value.details["candidates"] == [
        {"id": first.pk, "file_no": first.file_no, "reasons": ["phone"]}
    ]
    # Confirmed by the receptionist: the file is created anyway.
    second = _register(clerk, full_name_ar="شخص آخر", phone="0912000111", confirm=True)
    assert second.pk != first.pk


def test_duplicate_warning_on_similar_name_and_dob(clerk) -> None:
    dob = date(1985, 5, 5)
    first = _register(clerk, full_name_ar="فاطمة إبراهيم محمد", date_of_birth=dob)
    with pytest.raises(DomainError) as exc:
        _register(clerk, full_name_ar="فاطمه ابراهيم محمد", sex="female", date_of_birth=dob)
    assert exc.value.details["candidates"][0]["id"] == first.pk
    assert exc.value.details["candidates"][0]["reasons"] == ["name_dob"]
    # Same name, different date of birth: not a duplicate.
    other = _register(clerk, full_name_ar="فاطمة إبراهيم محمد", date_of_birth=date(1999, 1, 1))
    assert other.pk


def test_find_duplicates_ranks_strongest_first(clerk) -> None:
    dob = date(1970, 3, 3)
    a = _register(clerk, full_name_ar="حسن عبد الله", phone="0911111111", date_of_birth=dob)
    c = _register(clerk, full_name_ar="غير مشابه", phone_alt="0911111111", confirm=True)
    found = ps.find_duplicates(full_name_ar="حسن عبدالله", phone="0911111111", date_of_birth=dob)
    assert [f.patient.pk for f in found] == [a.pk, c.pk]
    assert found[0].reasons == ("phone", "name_dob")
    assert ps.find_duplicates(phone="0911111111", exclude_id=a.pk)[0].patient == c


def test_national_id_taken(clerk) -> None:
    _register(clerk, full_name_en="One", national_id="NID-1")
    with pytest.raises(DomainError) as exc:
        _register(clerk, full_name_en="Two", national_id="NID-1", confirm=True)
    assert exc.value.code == "NATIONAL_ID_TAKEN"


def test_emergency_registration_and_completion(clerk) -> None:
    p = ps.register_emergency(name="مجهول ١", sex="unknown", actor=clerk, age_years=40, today=TODAY)
    assert p.is_incomplete
    assert p.full_name_ar == "مجهول ١"
    assert p.dob_is_estimated
    en = ps.register_emergency(name="Unknown male", sex="male", actor=clerk)
    assert en.full_name_en == "Unknown male"
    with pytest.raises(DomainError):
        ps.register_emergency(name=" ", sex="male", actor=clerk)

    p = ps.update_patient(p, actor=clerk, sex="male", today=TODAY)
    assert p.is_incomplete  # still no exact birth date / phone
    p = ps.update_patient(
        p, actor=clerk, full_name_ar="عثمان  الطيب", date_of_birth=date(1980, 2, 2), phone="0123"
    )
    assert not p.is_incomplete
    assert p.full_name_ar == "عثمان الطيب"
    assert not p.dob_is_estimated
    with pytest.raises(DomainError) as exc:
        ps.update_patient(p, actor=clerk, file_no="X")
    assert exc.value.code == "FIELD_NOT_EDITABLE"


# --- search ---------------------------------------------------------------------------------


@pytest.fixture
def population(clerk):
    return {
        "ahmed": _register(
            clerk,
            full_name_ar="أحمد إبراهيم الطيب",
            full_name_en="Ahmed Ibrahim Eltayeb",
            phone="0912345678",
        ),
        "fatima": _register(
            clerk, full_name_ar="فاطمة مصطفى", sex="female", phone="0923456789", confirm=True
        ),
        "huda": _register(clerk, full_name_ar="هدى عيسى", sex="female", confirm=True),
    }


@pytest.mark.parametrize(
    ("query", "who"),
    [
        ("احمد ابراهيم", "ahmed"),
        ("أحمد", "ahmed"),
        ("ahmed eltayeb", "ahmed"),
        ("AHMED", "ahmed"),
        ("فاطمه", "fatima"),
        ("مصطفي", "fatima"),
        ("هدي عيسي", "huda"),
        ("هـدى", "huda"),
        ("0912345678", "ahmed"),
        ("+249 912 345 678", "ahmed"),
        ("٠٩٢٣٤٥٦٧٨٩", "fatima"),
        ("12345", "ahmed"),
    ],
)
def test_search_tolerates_spelling_variants(population, query: str, who: str) -> None:
    found = ps.search_patients(query)
    assert found
    assert found[0] == population[who]


def test_search_by_file_number_and_fuzzy(population) -> None:
    fatima = population["fatima"]
    assert ps.search_patients(fatima.file_no) == [fatima]
    assert ps.search_patients(fatima.file_no.lower()) == [fatima]
    # A typo beyond the letter folding still finds the name through trigram similarity.
    assert population["ahmed"] in ps.search_patients("Ahmad Ibrahim Eltayeb")
    assert ps.search_patients("   ") == []


# --- merge ----------------------------------------------------------------------------------


def test_merge_requires_permission_and_reason(clerk, supervisor) -> None:
    a = _register(clerk, full_name_ar="علي")
    c = _register(clerk, full_name_ar="علي", confirm=True)
    with pytest.raises(PermissionDenied):
        ps.merge_patients(a, c, actor=clerk, reason_note="dup")
    with pytest.raises(DomainError) as exc:
        ps.merge_patients(a, c, actor=supervisor, reason_note="  ")
    assert exc.value.code == "REASON_REQUIRED"
    with pytest.raises(DomainError) as exc:
        ps.merge_patients(a, a, actor=supervisor, reason_note="dup")
    assert exc.value.code == "MERGE_SAME_FILE"


def test_merge_keeps_history_and_moves_clinical_data(clerk, supervisor) -> None:
    payer = b.payer(requires_card_number=False)
    target = _register(clerk, full_name_ar="عائشة عمر", sex="female", phone="0911000000")
    source = _register(
        clerk,
        full_name_ar="عايشة عمر",
        full_name_en="Aisha Omer",
        sex="female",
        phone="0922000000",
        date_of_birth=date(1992, 4, 4),
        national_id="NID-77",
        confirm=True,
    )
    older = _register(clerk, full_name_en="Aisha O.", sex="female", confirm=True)
    ps.merge_patients(older, source, actor=supervisor, reason_note="same person")
    allergy = Allergy.objects.create(
        patient=source, allergen_type="food", substance="peanut", recorded_by=clerk
    )
    ps.add_coverage(source, payer=payer, actor=clerk)
    ps.add_coverage(target, payer=b.payer(requires_card_number=False), actor=clerk)
    visit = b.visit(source)
    appt = Appointment.objects.create(
        patient=source,
        doctor=b.doctor(),
        department=b.department(),
        starts_at=timezone.now() + timedelta(days=2),
        ends_at=timezone.now() + timedelta(days=2, minutes=15),
        created_by=clerk,
    )

    merge = ps.merge_patients(source, target, actor=supervisor, reason_note="same person")
    source.refresh_from_db()
    target.refresh_from_db()
    older.refresh_from_db()
    assert merge.source_snapshot["full_name_ar"] == "عايشة عمر"
    assert merge.merged_by == supervisor
    assert source.merged_into == target
    assert not source.is_active
    assert older.merged_into == target  # earlier merges resolve in one hop
    assert ps.resolve(older) == target
    assert set(ps.file_ids(target)) == {target.pk, source.pk, older.pk}
    # Gaps on the survivor were filled from the duplicate.
    assert target.full_name_en == "Aisha Omer"
    assert target.national_id == "NID-77"
    assert target.date_of_birth == date(1992, 4, 4)
    assert target.phone_alt == "0922000000"
    # Clinical safety data and coverage follow the person; the visit stays (it is billed).
    allergy.refresh_from_db()
    assert allergy.patient == target
    assert PatientCoverage.objects.filter(patient=target).count() == 2
    assert PatientCoverage.objects.filter(patient=target, is_default=True, active=True).count() == 1
    appt.refresh_from_db()
    assert appt.patient == target
    visit.refresh_from_db()
    assert visit.patient == source
    # Merged files leave search; they can be found on request.
    assert source not in ps.search_patients("عايشة عمر")
    assert source in ps.search_patients("عايشة عمر", include_inactive=True)
    with pytest.raises(DomainError) as exc:
        ps.merge_patients(source, target, actor=supervisor, reason_note="again")
    assert exc.value.code == "PATIENT_MERGED"
    with pytest.raises(DomainError) as exc:
        ps.update_patient(source, actor=clerk, phone="1")
    assert exc.value.code == "PATIENT_MERGED"
    assert PatientMerge.objects.count() == 2


# --- coverage -------------------------------------------------------------------------------


def test_coverage_on_file(clerk) -> None:
    p = _register(clerk, full_name_en="Covered")
    insurer = b.payer()
    with pytest.raises(DomainError) as exc:
        ps.add_coverage(p, payer=insurer, actor=clerk)
    assert exc.value.code == "CARD_NUMBER_REQUIRED"
    with pytest.raises(DomainError) as exc:
        ps.add_coverage(
            p,
            payer=insurer,
            actor=clerk,
            card_number="C1",
            valid_from=TODAY,
            valid_to=date(2026, 1, 1),
        )
    assert exc.value.code == "INVALID_DATE_RANGE"
    with pytest.raises(DomainError) as exc:
        ps.add_coverage(
            p, payer=insurer, actor=clerk, card_number="C1", patient_percent_override=Decimal(101)
        )
    assert exc.value.code == "INVALID_PERCENT"

    first = ps.add_coverage(
        p, payer=insurer, actor=clerk, card_number=" C-1 ", valid_to=TODAY + timedelta(days=30)
    )
    assert first.card_number == "C-1"
    assert ps.active_coverage(p, on=TODAY) == first
    assert ps.active_coverage(p, on=TODAY + timedelta(days=31)) is None
    second = ps.add_coverage(p, payer=b.payer(requires_card_number=False), actor=clerk)
    first.refresh_from_db()
    assert not first.is_default
    assert ps.active_coverage(p, on=TODAY) == second
    assert ps.active_coverage(p, on=TODAY, payer=insurer) == first
    assert set(ps.coverages_valid_on(p, TODAY)) == {first, second}
    ps.end_coverage(second, actor=clerk)
    assert ps.active_coverage(p, on=TODAY) is None
    inactive = b.payer(active=False)
    with pytest.raises(DomainError) as exc:
        ps.add_coverage(p, payer=inactive, actor=clerk, card_number="x")
    assert exc.value.code == "PAYER_INACTIVE"


def test_patient_count_unchanged_by_failed_registration(clerk) -> None:
    before = Patient.objects.count()
    with pytest.raises(DomainError):
        _register(clerk, full_name_ar="")
    assert Patient.objects.count() == before
