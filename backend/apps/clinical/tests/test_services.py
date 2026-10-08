"""Clinical services: allergies and prescribing alerts, notes, diagnoses, ICD-10, vitals,
referrals, order sets, nursing notes, patient summary."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone

from apps.clinical import services as cs
from apps.clinical.models import AllergyOverride, Icd10Code
from apps.core.tests import builders as b
from apps.orders.models import ServiceLine
from apps.patients import services as ps
from apps.pharmacy.models import DrugClass
from apps.visits.models import Visit
from domain.errors import DomainError

pytestmark = pytest.mark.django_db


@pytest.fixture
def doctor_user(make_user):
    return make_user(roles=["doctor"])


@pytest.fixture
def visit():
    return b.visit(b.patient(full_name_ar="خالد عثمان"))


@pytest.fixture
def penicillins():
    return DrugClass.objects.create(code="PEN", name_ar="البنسلينات", name_en="Penicillins")


@pytest.fixture
def amoxicillin(penicillins):
    it = b.item(generic_name="Amoxicillin", brand_name="Amoxil")
    it.drug_classes.add(penicillins)
    return it


# --- ICD-10 ---------------------------------------------------------------------------------


def test_icd10_seed_has_common_codes_with_arabic_titles() -> None:
    assert Icd10Code.objects.count() >= 300
    malaria = Icd10Code.objects.get(code="B54")
    assert malaria.title_ar == "الملاريا، غير محددة"
    assert malaria.chapter == "I"
    assert not Icd10Code.objects.filter(title_ar="").exists()


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("B54", "B54"),
        ("j18.9", "J18.9"),
        ("J189", "J18.9"),
        ("malaria", "B50.0"),
        ("ملاريا", "B50.0"),
        ("الملاريا", "B54"),
        ("السكري النوع الثاني", "E11.9"),
        ("hypertension essential", "I10"),
        ("تيفوئيد", "A01.0"),
    ],
)
def test_search_icd10(query: str, expected: str) -> None:
    found = [c.code for c in cs.search_icd10(query)]
    assert expected in found


def test_search_icd10_by_code_prefix_is_ordered() -> None:
    codes = [c.code for c in cs.search_icd10("J4")]
    assert codes == sorted(codes)
    assert all(c.startswith("J4") for c in codes)
    assert cs.search_icd10("   ") == []
    Icd10Code.objects.filter(code="B54").update(active=False)
    assert "B54" not in [c.code for c in cs.search_icd10("B5")]


# --- allergies ------------------------------------------------------------------------------


def test_allergy_alert_on_drug_class(doctor_user, visit, amoxicillin, penicillins) -> None:
    allergy = cs.record_allergy(
        visit.patient,
        actor=doctor_user,
        allergen_type="drug_class",
        drug_class=penicillins,
        reaction="rash",
        severity="severe",
    )
    alerts = cs.allergy_alerts(visit.patient, [amoxicillin.service])
    assert alerts == [
        cs.AllergyAlert(amoxicillin.service_id, allergy.pk, "drug_class", "severe", "Penicillins")
    ]
    # Other drugs and non-drug services raise nothing.
    assert cs.allergy_alerts(visit.patient, [b.item().service, b.service("lab")]) == []
    # A resolved allergy no longer alerts.
    cs.set_allergy_status(allergy, status="inactive", actor=doctor_user)
    assert cs.allergy_alerts(visit.patient, [amoxicillin.service]) == []


def test_allergy_alert_on_item_and_substance(doctor_user, visit, amoxicillin) -> None:
    cs.record_allergy(visit.patient, actor=doctor_user, allergen_type="drug", item=amoxicillin)
    cs.record_allergy(visit.patient, actor=doctor_user, allergen_type="drug", substance="AMOXIL")
    matches = sorted(a.match for a in cs.allergy_alerts(visit.patient, [amoxicillin.service]))
    assert matches == ["item", "substance"]


def test_allergies_follow_merged_files(doctor_user, make_user, amoxicillin, penicillins) -> None:
    survivor, duplicate = b.patient(), b.patient()
    cs.record_allergy(
        duplicate, actor=doctor_user, allergen_type="drug_class", drug_class=penicillins
    )
    ps.merge_patients(duplicate, survivor, actor=make_user(roles=["manager"]), reason_note="d")
    assert cs.allergy_alerts(survivor, [amoxicillin.service])
    # Recording on a merged file lands on the survivor.
    later = cs.record_allergy(duplicate, actor=doctor_user, allergen_type="food", substance="egg")
    assert later.patient == survivor


def test_record_allergy_validation(doctor_user, visit) -> None:
    cases: list[tuple[dict[str, Any], str]] = [
        ({"allergen_type": "drug_class"}, "DRUG_CLASS_REQUIRED"),
        ({"allergen_type": "food"}, "ALLERGEN_REQUIRED"),
        ({"allergen_type": "bogus", "substance": "x"}, "INVALID_ALLERGEN_TYPE"),
        ({"allergen_type": "food", "substance": "x", "severity": "huge"}, "INVALID_SEVERITY"),
    ]
    for kwargs, code in cases:
        with pytest.raises(DomainError) as exc:
            cs.record_allergy(visit.patient, actor=doctor_user, **kwargs)
        assert exc.value.code == code


def test_ordering_a_flagged_drug_is_a_conflict_without_a_reason(
    doctor_user, visit, amoxicillin, penicillins
) -> None:
    cs.record_allergy(
        visit.patient, actor=doctor_user, allergen_type="drug_class", drug_class=penicillins
    )
    for reason in ("", "   "):
        with pytest.raises(DomainError) as exc:
            cs.order_lines(
                visit,
                [{"service": amoxicillin.service}],
                actor=doctor_user,
                allergy_override_reason=reason,
            )
        assert exc.value.code == "ALLERGY_CONFLICT"
    assert exc.value.details["alerts"][0]["match"] == "drug_class"
    assert not ServiceLine.objects.filter(visit=visit).exists()
    assert not AllergyOverride.objects.exists()
    with pytest.raises(DomainError) as exc:
        cs.order_lines(visit, [], actor=doctor_user)
    assert exc.value.code == "ORDER_EMPTY"


def test_overridden_order_records_reason_approver_and_time(
    doctor_user, visit, amoxicillin, penicillins
) -> None:
    allergy = cs.record_allergy(
        visit.patient, actor=doctor_user, allergen_type="drug_class", drug_class=penicillins
    )
    cbc = b.service("lab")
    before = timezone.now()
    lines = cs.order_lines(
        visit,
        [{"service": amoxicillin.service, "quantity": Decimal(10)}, {"service": cbc.pk}],
        actor=doctor_user,
        allergy_override_reason="  tolerated amoxicillin last year  ",
    )
    drug = ServiceLine.objects.get(visit=visit, service=amoxicillin.service)
    assert drug.billing_status == "unbilled"
    assert [ln.service_id for ln in lines] == [amoxicillin.service_id, cbc.pk]
    override = AllergyOverride.objects.get()
    assert override.service_line == drug
    assert override.allergy == allergy
    assert override.match == "drug_class"
    assert override.reason == "tolerated amoxicillin last year"
    assert override.overridden_by == doctor_user
    assert override.overridden_at >= before
    # The override is the audit record: it never changes.
    b.db_rejects(
        lambda: AllergyOverride.objects.filter(pk=override.pk).update(reason="x"), "APPEND_ONLY"
    )
    # A reason with no conflict records nothing.
    cs.order_lines(visit, [{"service": cbc}], actor=doctor_user, allergy_override_reason="n/a")
    assert AllergyOverride.objects.count() == 1


def test_prescription_fills_the_quantity(doctor_user, visit, amoxicillin) -> None:
    (line,) = cs.order_lines(
        visit,
        [
            {
                "service": amoxicillin.service,
                "prescription": {
                    "dose": "1 capsule",
                    "dose_quantity": Decimal(1),
                    "frequency_code": "tid",
                    "duration_days": 7,
                },
            }
        ],
        actor=doctor_user,
    )
    assert line.quantity == Decimal(21)
    assert line.prescription.frequency_code == "TID"
    assert line.prescription.frequency_per_day == Decimal(3)
    # A stated quantity wins (a whole pack); an uncountable course needs one.
    (packed,) = cs.order_lines(
        visit,
        [
            {
                "service": amoxicillin.service,
                "quantity": 30,
                "prescription": {"dose": "1", "dose_quantity": 1, "frequency_code": "TID"},
            }
        ],
        actor=doctor_user,
    )
    assert packed.quantity == Decimal(30)
    cases: list[tuple[dict[str, Any], str]] = [
        ({"dose": "1", "dose_quantity": 1, "frequency_code": "PRN"}, "QUANTITY_REQUIRED"),
        ({"dose": "1", "frequency_code": "WHENEVER", "duration_days": 2}, "UNKNOWN_FREQUENCY"),
        (
            {"dose": "1", "dose_quantity": 1, "frequency_code": "TID", "frequency_per_day": 2},
            "FREQUENCY_MISMATCH",
        ),
        (
            {"dose": "1", "dose_quantity": 1, "frequency_per_day": 1, "duration_days": 999},
            "INVALID_PRESCRIPTION",
        ),
        ({"dose": "1", "dose_quantity": 1.5, "frequency_code": "OD"}, "INVALID_PRESCRIPTION"),
    ]
    for rx, code in cases:
        with pytest.raises(DomainError) as exc:
            cs.order_lines(
                visit, [{"service": amoxicillin.service, "prescription": rx}], actor=doctor_user
            )
        assert exc.value.code == code, rx
    with pytest.raises(DomainError) as exc:
        cs.order_lines(
            visit, [{"service": b.service("lab"), "prescription": {"dose": "1"}}], actor=doctor_user
        )
    assert exc.value.code == "PRESCRIPTION_NOT_DRUG"


def test_prescription_quantity() -> None:
    assert (
        cs.prescription_quantity(
            dose_quantity=Decimal(1), frequency_per_day=Decimal(3), duration_days=5
        )
        == 15
    )
    assert (
        cs.prescription_quantity(
            dose_quantity=Decimal("0.5"), frequency_per_day=Decimal(3), duration_days=5
        )
        == 8
    )
    with pytest.raises(DomainError):
        cs.prescription_quantity(
            dose_quantity=Decimal(0), frequency_per_day=Decimal(1), duration_days=1
        )


def test_chronic_conditions(doctor_user, visit) -> None:
    dm = Icd10Code.objects.get(code="E11.9")
    cond = cs.record_condition(visit.patient, actor=doctor_user, icd10=dm)
    with pytest.raises(DomainError) as exc:
        cs.record_condition(visit.patient, actor=doctor_user)
    assert exc.value.code == "CONDITION_NAME_REQUIRED"
    assert cs.set_condition_status(cond, status="inactive", actor=doctor_user).status == "inactive"


# --- notes and diagnoses --------------------------------------------------------------------


def test_note_draft_sign_and_immutability(doctor_user, make_user, visit) -> None:
    note = cs.save_note(visit, actor=doctor_user, complaint="fever 3 days")
    note = cs.save_note(visit, note=note, actor=doctor_user, plan="malaria test")
    assert note.plan == "malaria test"
    other = make_user(roles=["doctor"])
    with pytest.raises(DomainError) as exc:
        cs.save_note(visit, note=note, actor=other, plan="x")
    assert exc.value.code == "NOTE_NOT_AUTHOR"
    with pytest.raises(DomainError) as exc:
        cs.save_note(visit, actor=doctor_user, price="1")
    assert exc.value.code == "FIELD_NOT_EDITABLE"
    signed = cs.sign_note(note, actor=doctor_user)
    assert signed.status == "signed"
    assert signed.signed_at
    with pytest.raises(DomainError) as exc:
        cs.save_note(visit, note=note, actor=doctor_user, plan="changed")
    assert exc.value.code == "NOTE_SIGNED"
    empty = cs.save_note(visit, actor=doctor_user)
    with pytest.raises(DomainError) as exc:
        cs.sign_note(empty, actor=doctor_user)
    assert exc.value.code == "NOTE_EMPTY"


def test_diagnoses(doctor_user, visit) -> None:
    note = cs.save_note(visit, actor=doctor_user, assessment="malaria")
    d = cs.add_diagnosis(visit, actor=doctor_user, icd10_code="b54", note=note)
    assert d.icd10 is not None
    assert d.icd10.code == "B54"
    free = cs.add_diagnosis(visit, actor=doctor_user, text="  viral fever ", kind="secondary")
    assert free.text == "viral fever"
    with pytest.raises(DomainError) as exc:
        cs.add_diagnosis(visit, actor=doctor_user, icd10_code="ZZZ.9")
    assert exc.value.code == "ICD10_UNKNOWN"
    with pytest.raises(DomainError) as exc:
        cs.add_diagnosis(visit, actor=doctor_user)
    assert exc.value.code == "DIAGNOSIS_REQUIRED"
    with pytest.raises(DomainError) as exc:
        cs.add_diagnosis(b.visit(), actor=doctor_user, text="x", note=note)
    assert exc.value.code == "NOTE_NOT_ON_VISIT"
    Visit.objects.filter(pk=visit.pk).update(status="closed", closed_at=timezone.now())
    visit.refresh_from_db()
    with pytest.raises(DomainError) as exc:
        cs.add_diagnosis(visit, actor=doctor_user, text="late")
    assert exc.value.code == "VISIT_NOT_OPEN"


# --- vitals ---------------------------------------------------------------------------------


def test_vitals(make_user, visit) -> None:
    nurse = make_user(roles=["nurse"])
    v = cs.record_vitals(
        visit,
        actor=nurse,
        temperature_c=Decimal("38.4"),
        pulse_bpm=96,
        bp_systolic=130,
        bp_diastolic=85,
        spo2_percent=97,
    )
    assert v.recorded_by == nurse
    assert v.temperature_c == Decimal("38.4")
    cases: list[tuple[dict[str, Any], str]] = [
        ({}, "VITALS_EMPTY"),
        ({"temperature_c": Decimal(50)}, "VITALS_OUT_OF_RANGE"),
        ({"spo2_percent": 101}, "VITALS_OUT_OF_RANGE"),
        ({"bp_systolic": 120}, "BP_INCOMPLETE"),
        ({"bp_systolic": 80, "bp_diastolic": 90}, "VITALS_OUT_OF_RANGE"),
        ({"blood_pressure": 1}, "FIELD_NOT_EDITABLE"),
    ]
    for measures, code in cases:
        with pytest.raises(DomainError) as exc:
            cs.record_vitals(visit, actor=nurse, **measures)
        assert exc.value.code == code, measures
    with pytest.raises(DomainError) as exc:
        cs.record_vitals(
            visit, actor=nurse, pulse_bpm=80, recorded_at=timezone.now() + timedelta(hours=1)
        )
    assert exc.value.code == "INVALID_TIME"


# --- referrals ------------------------------------------------------------------------------


def test_referrals(doctor_user, visit) -> None:
    surgeon = b.doctor()
    internal = cs.create_referral(
        visit, actor=doctor_user, kind="internal", to_doctor=surgeon, reason="hernia"
    )
    assert internal.to_department == surgeon.department
    external = cs.create_referral(
        visit,
        actor=doctor_user,
        kind="external",
        external_facility="Khartoum Teaching Hospital",
        reason="CT scan",
        urgency="urgent",
    )
    referral_cases: list[tuple[dict[str, Any], str]] = [
        ({"kind": "internal", "reason": "x"}, "DEPARTMENT_REQUIRED"),
        ({"kind": "external", "reason": "x"}, "FACILITY_REQUIRED"),
        ({"kind": "external", "reason": " ", "external_facility": "y"}, "REASON_REQUIRED"),
        ({"kind": "sideways", "reason": "x"}, "INVALID_REFERRAL_KIND"),
    ]
    for kwargs, code in referral_cases:
        with pytest.raises(DomainError) as exc:
            cs.create_referral(visit, actor=doctor_user, **kwargs)
        assert exc.value.code == code
    assert cs.complete_referral(internal, actor=doctor_user).status == "completed"
    assert cs.cancel_referral(external, actor=doctor_user).status == "cancelled"
    with pytest.raises(DomainError) as exc:
        cs.cancel_referral(internal, actor=doctor_user)
    assert exc.value.code == "REFERRAL_CLOSED"


# --- order sets -----------------------------------------------------------------------------


def test_order_sets_and_favorites(doctor_user, make_user) -> None:
    cbc, malaria, para = b.service("lab"), b.service("lab"), b.service("drug")
    dept = b.department()
    shared = cs.create_order_set(
        name_ar="حمى",
        name_en="Fever work-up",
        items=[
            {"service": cbc, "instructions": "fasting"},
            {"service": malaria, "quantity": 1},
            {"service": para, "quantity": 9, "dose": "1 tab", "frequency_code": "TID"},
        ],
        actor=doctor_user,
        personal=False,
        department=dept,
    )
    mine = cs.create_order_set(
        name_ar="مفضلتي", name_en="", items=[{"service": cbc}], actor=doctor_user
    )
    other_doctor = make_user(roles=["doctor"])
    cs.create_order_set(name_ar="له", name_en="His", items=[{"service": cbc}], actor=other_doctor)
    visible = set(cs.order_sets_for(doctor_user, department=dept))
    assert visible == {shared, mine}
    assert set(cs.order_sets_for(doctor_user, department=b.department())) == {mine}
    items = cs.order_set_items(shared)
    assert [i["service"] for i in items] == [cbc, malaria, para]
    assert items[0]["note"] == "fasting"
    assert "prescription" not in items[1]
    assert items[2]["prescription"]["frequency_code"] == "TID"
    assert items[2]["quantity"] == 9
    cbc.active = False
    cbc.save()
    assert [i["service"] for i in cs.order_set_items(shared)] == [malaria, para]
    with pytest.raises(DomainError) as exc:
        cs.create_order_set(name_ar="x", name_en="", items=[], actor=doctor_user)
    assert exc.value.code == "ORDER_EMPTY"
    with pytest.raises(DomainError) as exc:
        cs.create_order_set(
            name_ar="x", name_en="", items=[{"service": malaria, "price": 1}], actor=doctor_user
        )
    assert exc.value.code == "FIELD_NOT_EDITABLE"


# --- nursing notes and summary --------------------------------------------------------------


def test_nursing_note(make_user, visit) -> None:
    nurse = make_user(roles=["nurse"])
    line = b.service_line(visit, b.service("procedure"))
    note = cs.add_nursing_note(
        visit, actor=nurse, text="dressing changed", kind="procedure", service_line=line
    )
    assert note.author == nurse
    with pytest.raises(DomainError) as exc:
        cs.add_nursing_note(visit, actor=nurse, text=" ")
    assert exc.value.code == "NOTE_EMPTY"
    with pytest.raises(DomainError) as exc:
        cs.add_nursing_note(b.visit(), actor=nurse, text="x", service_line=line)
    assert exc.value.code == "LINE_NOT_ON_VISIT"


def test_patient_summary(doctor_user, visit, amoxicillin, penicillins) -> None:
    patient = visit.patient
    cs.record_allergy(
        patient, actor=doctor_user, allergen_type="drug_class", drug_class=penicillins
    )
    gone = cs.record_allergy(patient, actor=doctor_user, allergen_type="food", substance="milk")
    cs.set_allergy_status(gone, status="entered_in_error", actor=doctor_user)
    cs.record_condition(patient, actor=doctor_user, name="Hypertension")
    for _ in range(6):
        b.visit(patient)
    b.service_line(visit, amoxicillin.service)
    summary = cs.patient_summary(patient)
    assert [a.drug_class for a in summary.allergies] == [penicillins]
    assert [c.name for c in summary.conditions] == ["Hypertension"]
    assert len(summary.recent_visits) == 5
    assert [ln.service for ln in summary.active_medications] == [amoxicillin.service]
    assert summary.latest_results == []
