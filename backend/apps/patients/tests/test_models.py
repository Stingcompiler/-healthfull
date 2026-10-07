"""Patient files: normalized search columns, merge history, coverage (FEATURES 0.9, 1)."""

from __future__ import annotations

from datetime import date

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.models import Value

from apps.core.db import NormalizePhone, NormalizeText
from apps.core.tests import builders as b
from apps.patients.models import Patient, PatientCoverage, PatientMerge

pytestmark = pytest.mark.django_db


def test_search_columns_are_generated_and_normalized() -> None:
    pat = b.patient(
        full_name_ar="أَحْمَدُ  عبدالله", full_name_en="Ahmed ABDALLA", phone="+249 912-345-678"
    )
    pat.refresh_from_db()
    assert pat.search_name == "احمد عبدالله ahmed abdalla"
    assert pat.phone_norm == "0912345678"
    assert pat.phone_alt_norm == ""


def test_spelling_variants_find_the_same_patient() -> None:
    pat = b.patient(full_name_ar="فاطمة إبراهيم", phone="٠٩١٢٣٤٥٦٧٨")
    for query in ("فاطمه ابراهيم", "فاطمة إبراهيم", "ابراهيم"):
        found = Patient.objects.filter(search_name__contains=NormalizeText(Value(query)))
        assert pat in found, query
    assert pat in Patient.objects.filter(phone_norm=NormalizePhone(Value("00249912345678")))
    assert pat in Patient.objects.filter(search_name__trigram_similar="فاطمه ابراهيم")


def test_search_indexes_exist() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'patients_patient'"
        )
        indexes = dict(cursor.fetchall())
    assert "gin_trgm_ops" in indexes["patients_patient_name_trgm"]
    assert "gin_trgm_ops" in indexes["patients_patient_phone_trgm"]
    assert "patients_patient_phone_idx" in indexes


def test_patient_needs_a_name_and_a_valid_sex() -> None:
    with pytest.raises(IntegrityError, match="patients_patient_has_name"), transaction.atomic():
        b.patient(full_name_ar="", full_name_en="")
    with pytest.raises(IntegrityError, match="patients_patient_sex_valid"), transaction.atomic():
        b.patient(sex="x")
    b.patient(full_name_ar="", full_name_en="Unknown", sex="unknown", is_incomplete=True)


def test_national_id_unique_among_unmerged_files() -> None:
    b.patient(national_id="123")
    b.patient(national_id="")
    b.patient(national_id="")
    with (
        pytest.raises(IntegrityError, match="patients_patient_national_id_unique"),
        transaction.atomic(),
    ):
        b.patient(national_id="123")


def test_merge_rules_and_history_is_append_only() -> None:
    source, target = b.patient(), b.patient()
    with (
        pytest.raises(IntegrityError, match="patients_patient_merged_is_inactive"),
        transaction.atomic(),
    ):
        Patient.objects.filter(pk=source.pk).update(merged_into=target)
    with (
        pytest.raises(IntegrityError, match="patients_patient_not_merged_into_self"),
        transaction.atomic(),
    ):
        Patient.objects.filter(pk=source.pk).update(merged_into=source, is_active=False)
    Patient.objects.filter(pk=source.pk).update(merged_into=target, is_active=False)
    merge = PatientMerge.objects.create(
        source=source, target=target, reason_note="same person", merged_by=b.user()
    )
    b.db_rejects(
        lambda: PatientMerge.objects.filter(pk=merge.pk).update(reason_note="x"), "APPEND_ONLY"
    )
    b.db_rejects(lambda: PatientMerge.objects.filter(pk=merge.pk).delete(), "APPEND_ONLY")
    b.sql_rejects("DELETE FROM patients_patientmerge WHERE id = %s", [merge.pk], "APPEND_ONLY")
    with (
        pytest.raises(IntegrityError, match="patients_merge_reason_required"),
        transaction.atomic(),
    ):
        PatientMerge.objects.create(
            source=b.patient(), target=target, reason_note="", merged_by=b.user()
        )


def test_one_default_active_coverage_per_patient() -> None:
    pat, payer = b.patient(), b.payer()
    PatientCoverage.objects.create(patient=pat, payer=payer, card_number="C1")
    with pytest.raises(IntegrityError, match="patients_coverage_one_default"), transaction.atomic():
        PatientCoverage.objects.create(patient=pat, payer=b.payer(), card_number="C2")
    PatientCoverage.objects.create(patient=pat, payer=b.payer(), is_default=False)
    with pytest.raises(IntegrityError, match="patients_coverage_valid_dates"), transaction.atomic():
        PatientCoverage.objects.create(
            patient=b.patient(),
            payer=payer,
            valid_from=date(2026, 2, 1),
            valid_to=date(2026, 1, 1),
        )
