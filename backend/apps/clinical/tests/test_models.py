"""Clinical records: shape constraints (FEATURES 3)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.clinical.models import (
    Allergy,
    ChronicCondition,
    ClinicalNote,
    Diagnosis,
    Icd10Code,
    NursingNote,
    OrderSet,
    OrderSetItem,
    Referral,
    Vitals,
)
from apps.core.tests import builders as b
from apps.pharmacy.models import DrugClass

pytestmark = pytest.mark.django_db


def test_drug_class_allergy_names_its_class() -> None:
    pat = b.patient()
    with pytest.raises(IntegrityError, match="clinical_allergy_class_named"), transaction.atomic():
        Allergy.objects.create(
            patient=pat,
            allergen_type="drug_class",
            substance="penicillin",
            recorded_by=b.user(),
        )
    penicillins = DrugClass.objects.create(code="PEN", name_ar="البنسلينات", name_en="Penicillins")
    Allergy.objects.create(
        patient=pat, allergen_type="drug_class", drug_class=penicillins, recorded_by=b.user()
    )
    with pytest.raises(IntegrityError, match="clinical_allergy_has_allergen"), transaction.atomic():
        Allergy.objects.create(patient=pat, allergen_type="food", recorded_by=b.user())


def test_vitals_are_plausible() -> None:
    v = b.visit()
    Vitals.objects.create(
        visit=v,
        temperature_c=Decimal("37.2"),
        pulse_bpm=80,
        bp_systolic=120,
        bp_diastolic=80,
        spo2_percent=98,
        recorded_by=b.user(),
        recorded_at=timezone.now(),
    )
    for kw, name in (
        ({"temperature_c": Decimal("98.6")}, "clinical_vitals_temperature_range"),
        ({"spo2_percent": 120}, "clinical_vitals_spo2_range"),
        ({"pain_score": 11}, "clinical_vitals_pain_range"),
        ({"weight_kg": Decimal("0")}, "clinical_vitals_body_range"),
    ):
        with pytest.raises(IntegrityError, match=name), transaction.atomic():
            Vitals.objects.create(visit=v, recorded_by=b.user(), recorded_at=timezone.now(), **kw)


def test_notes_diagnoses_and_conditions() -> None:
    v = b.visit()
    note = ClinicalNote.objects.create(visit=v, author=b.user(), complaint="headache")
    b.db_rejects(
        lambda: ClinicalNote.objects.filter(pk=note.pk).update(status="signed"),
        "clinical_note_signed_has_time",
    )
    icd = Icd10Code.objects.get_or_create(code="R51", defaults={"title_en": "Headache"})[0]
    Diagnosis.objects.create(visit=v, note=note, icd10=icd, recorded_by=b.user())
    with pytest.raises(IntegrityError, match="clinical_diagnosis_named"), transaction.atomic():
        Diagnosis.objects.create(visit=v, recorded_by=b.user())
    with pytest.raises(IntegrityError, match="clinical_condition_named"), transaction.atomic():
        ChronicCondition.objects.create(patient=v.patient, recorded_by=b.user())
    with pytest.raises(IntegrityError, match="clinical_nursingnote_has_text"), transaction.atomic():
        NursingNote.objects.create(visit=v, text="", author=b.user())


def test_referral_destination() -> None:
    v = b.visit()
    with (
        pytest.raises(IntegrityError, match="clinical_referral_internal_has_department"),
        transaction.atomic(),
    ):
        Referral.objects.create(visit=v, kind="internal", reason="x", referred_by=b.user())
    with (
        pytest.raises(IntegrityError, match="clinical_referral_external_has_facility"),
        transaction.atomic(),
    ):
        Referral.objects.create(visit=v, kind="external", reason="x", referred_by=b.user())
    Referral.objects.create(
        visit=v, kind="external", external_facility="Ibn Sina", reason="CT", referred_by=b.user()
    )


def test_order_set_items() -> None:
    order_set = OrderSet.objects.create(name_ar="حمى", name_en="Fever", owner=b.user())
    OrderSetItem.objects.create(order_set=order_set, service=b.service())
    with (
        pytest.raises(IntegrityError, match="clinical_orderset_qty_positive"),
        transaction.atomic(),
    ):
        OrderSetItem.objects.create(order_set=order_set, service=b.service(), quantity=Decimal("0"))
