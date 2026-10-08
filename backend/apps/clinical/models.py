"""Clinical records written by doctors and nurses (FEATURES 3, 10.3).

None of these models carries prices or billing state: doctors never see billing (FEATURES 3.8).
"""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import Q

from apps.core.db import choice_check, quantity_field, track_history


@track_history()
class Icd10Code(models.Model):
    """ICD-10 lookup table (FEATURES 3.3); loaded by import, searched by code or title."""

    code = models.CharField(max_length=10, unique=True)
    title_en = models.CharField(max_length=300)
    title_ar = models.CharField(max_length=300, blank=True)
    chapter = models.CharField(max_length=10, blank=True)
    is_leaf = models.BooleanField(default=True, help_text="Billable leaf code.")
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "ICD-10 code"
        ordering: ClassVar[list[str]] = ["code"]
        indexes: ClassVar[list[models.Index]] = [
            GinIndex(
                fields=["title_en"], opclasses=["gin_trgm_ops"], name="clinical_icd10_en_trgm"
            ),
            GinIndex(
                fields=["title_ar"], opclasses=["gin_trgm_ops"], name="clinical_icd10_ar_trgm"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.title_en}"


class AllergenType(models.TextChoices):
    DRUG = "drug", "Specific drug"
    DRUG_CLASS = "drug_class", "Drug class"
    FOOD = "food", "Food"
    ENVIRONMENTAL = "environmental", "Environmental"
    OTHER = "other", "Other"


class Severity(models.TextChoices):
    MILD = "mild", "Mild"
    MODERATE = "moderate", "Moderate"
    SEVERE = "severe", "Severe"
    LIFE_THREATENING = "life_threatening", "Life-threatening"


class RecordStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive / resolved"
    ERROR = "entered_in_error", "Entered in error"


@track_history()
class Allergy(models.Model):
    """Allergy registry; drug and drug-class entries drive prescribing alerts (FEATURES 3.2)."""

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="allergies"
    )
    allergen_type = models.CharField(max_length=20, choices=AllergenType.choices)
    drug_class = models.ForeignKey(
        "pharmacy.DrugClass", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    item = models.ForeignKey(
        "pharmacy.Item", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    substance = models.CharField(max_length=200, blank=True, help_text="As described.")
    reaction = models.CharField(max_length=300, blank=True)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.MODERATE)
    status = models.CharField(
        max_length=20, choices=RecordStatus.choices, default=RecordStatus.ACTIVE
    )
    note = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "allergy"
        verbose_name_plural = "allergies"
        ordering: ClassVar[list[str]] = ["patient", "-recorded_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("allergen_type", AllergenType, "clinical_allergy_type_valid"),
            choice_check("severity", Severity, "clinical_allergy_severity_valid"),
            choice_check("status", RecordStatus, "clinical_allergy_status_valid"),
            models.CheckConstraint(
                condition=~Q(allergen_type=AllergenType.DRUG_CLASS) | Q(drug_class__isnull=False),
                name="clinical_allergy_class_named",
            ),
            models.CheckConstraint(
                condition=Q(drug_class__isnull=False) | Q(item__isnull=False) | ~Q(substance=""),
                name="clinical_allergy_has_allergen",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["patient", "status"], name="clinical_allergy_patient_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.patient_id}: {self.substance or self.drug_class_id or self.item_id}"


@track_history()
class ChronicCondition(models.Model):
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.PROTECT, related_name="chronic_conditions"
    )
    icd10 = models.ForeignKey(
        Icd10Code, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    name = models.CharField(max_length=200, blank=True)
    since = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=RecordStatus.choices, default=RecordStatus.ACTIVE
    )
    note = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "chronic condition"
        ordering: ClassVar[list[str]] = ["patient", "-recorded_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", RecordStatus, "clinical_condition_status_valid"),
            models.CheckConstraint(
                condition=Q(icd10__isnull=False) | ~Q(name=""), name="clinical_condition_named"
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["patient", "status"], name="clinical_condition_patient_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.patient_id}: {self.name or self.icd10_id}"


class NoteStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SIGNED = "signed", "Signed"


@track_history()
class ClinicalNote(models.Model):
    """Complaint, examination, assessment and plan for a visit (FEATURES 3.3)."""

    visit = models.ForeignKey(
        "visits.Visit", on_delete=models.PROTECT, related_name="clinical_notes"
    )
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    complaint = models.TextField(blank=True)
    history = models.TextField(blank=True)
    examination = models.TextField(blank=True)
    assessment = models.TextField(blank=True)
    plan = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=NoteStatus.choices, default=NoteStatus.DRAFT)
    signed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "clinical note"
        ordering: ClassVar[list[str]] = ["visit", "created_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", NoteStatus, "clinical_note_status_valid"),
            models.CheckConstraint(
                condition=~Q(status=NoteStatus.SIGNED) | Q(signed_at__isnull=False),
                name="clinical_note_signed_has_time",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["visit"], name="clinical_note_visit_idx"),
        ]

    def __str__(self) -> str:
        return f"note {self.pk} visit {self.visit_id}"


class DiagnosisKind(models.TextChoices):
    PRIMARY = "primary", "Primary"
    SECONDARY = "secondary", "Secondary"


class Certainty(models.TextChoices):
    PROVISIONAL = "provisional", "Provisional"
    CONFIRMED = "confirmed", "Confirmed"


@track_history()
class Diagnosis(models.Model):
    visit = models.ForeignKey("visits.Visit", on_delete=models.PROTECT, related_name="diagnoses")
    note = models.ForeignKey(
        ClinicalNote, on_delete=models.PROTECT, null=True, blank=True, related_name="diagnoses"
    )
    icd10 = models.ForeignKey(
        Icd10Code, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    text = models.CharField(max_length=300, blank=True)
    kind = models.CharField(
        max_length=10, choices=DiagnosisKind.choices, default=DiagnosisKind.PRIMARY
    )
    certainty = models.CharField(
        max_length=15, choices=Certainty.choices, default=Certainty.PROVISIONAL
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "diagnosis"
        verbose_name_plural = "diagnoses"
        ordering: ClassVar[list[str]] = ["visit", "kind", "recorded_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("kind", DiagnosisKind, "clinical_diagnosis_kind_valid"),
            choice_check("certainty", Certainty, "clinical_diagnosis_certainty_valid"),
            models.CheckConstraint(
                condition=Q(icd10__isnull=False) | ~Q(text=""), name="clinical_diagnosis_named"
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["icd10", "recorded_at"], name="clinical_diagnosis_icd_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.visit_id}: {self.icd10_id or self.text}"


@track_history()
class Vitals(models.Model):
    """Vital signs by nurse or doctor (FEATURES 3.4). Every measure optional, plausible-ranged."""

    visit = models.ForeignKey("visits.Visit", on_delete=models.PROTECT, related_name="vitals")
    temperature_c = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    pulse_bpm = models.PositiveSmallIntegerField(null=True, blank=True)
    respiratory_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    bp_systolic = models.PositiveSmallIntegerField(null=True, blank=True)
    bp_diastolic = models.PositiveSmallIntegerField(null=True, blank=True)
    spo2_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    blood_glucose_mg_dl = models.PositiveSmallIntegerField(null=True, blank=True)
    pain_score = models.PositiveSmallIntegerField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    recorded_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "vitals"
        verbose_name_plural = "vitals"
        ordering: ClassVar[list[str]] = ["visit", "-recorded_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(temperature_c__isnull=True)
                | (Q(temperature_c__gte=25) & Q(temperature_c__lte=45)),
                name="clinical_vitals_temperature_range",
            ),
            models.CheckConstraint(
                condition=Q(pulse_bpm__isnull=True) | Q(pulse_bpm__lte=300),
                name="clinical_vitals_pulse_range",
            ),
            models.CheckConstraint(
                condition=Q(respiratory_rate__isnull=True) | Q(respiratory_rate__lte=120),
                name="clinical_vitals_rr_range",
            ),
            models.CheckConstraint(
                condition=(Q(bp_systolic__isnull=True) | Q(bp_systolic__lte=350))
                & (Q(bp_diastolic__isnull=True) | Q(bp_diastolic__lte=250)),
                name="clinical_vitals_bp_range",
            ),
            models.CheckConstraint(
                condition=Q(spo2_percent__isnull=True) | Q(spo2_percent__lte=100),
                name="clinical_vitals_spo2_range",
            ),
            models.CheckConstraint(
                condition=(Q(weight_kg__isnull=True) | (Q(weight_kg__gt=0) & Q(weight_kg__lte=500)))
                & (Q(height_cm__isnull=True) | (Q(height_cm__gt=0) & Q(height_cm__lte=272))),
                name="clinical_vitals_body_range",
            ),
            models.CheckConstraint(
                condition=Q(pain_score__isnull=True) | Q(pain_score__lte=10),
                name="clinical_vitals_pain_range",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["visit", "-recorded_at"], name="clinical_vitals_visit_idx"),
        ]

    def __str__(self) -> str:
        return f"vitals {self.pk} visit {self.visit_id}"


class ReferralKind(models.TextChoices):
    INTERNAL = "internal", "Another department"
    EXTERNAL = "external", "External facility"


class Urgency(models.TextChoices):
    ROUTINE = "routine", "Routine"
    URGENT = "urgent", "Urgent"
    EMERGENCY = "emergency", "Emergency"


class ReferralStatus(models.TextChoices):
    ISSUED = "issued", "Issued"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


@track_history()
class Referral(models.Model):
    """Referral note to another department or an external facility (FEATURES 3.9)."""

    visit = models.ForeignKey("visits.Visit", on_delete=models.PROTECT, related_name="referrals")
    kind = models.CharField(max_length=10, choices=ReferralKind.choices)
    to_department = models.ForeignKey(
        "core.Department", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    to_doctor = models.ForeignKey(
        "core.DoctorProfile", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    external_facility = models.CharField(max_length=200, blank=True)
    reason = models.TextField()
    clinical_summary = models.TextField(blank=True)
    urgency = models.CharField(max_length=10, choices=Urgency.choices, default=Urgency.ROUTINE)
    status = models.CharField(
        max_length=10, choices=ReferralStatus.choices, default=ReferralStatus.ISSUED
    )
    referred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "referral"
        ordering: ClassVar[list[str]] = ["-created_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("kind", ReferralKind, "clinical_referral_kind_valid"),
            choice_check("urgency", Urgency, "clinical_referral_urgency_valid"),
            choice_check("status", ReferralStatus, "clinical_referral_status_valid"),
            models.CheckConstraint(
                condition=~Q(kind=ReferralKind.INTERNAL) | Q(to_department__isnull=False),
                name="clinical_referral_internal_has_department",
            ),
            models.CheckConstraint(
                condition=~Q(kind=ReferralKind.EXTERNAL) | ~Q(external_facility=""),
                name="clinical_referral_external_has_facility",
            ),
            models.CheckConstraint(condition=~Q(reason=""), name="clinical_referral_has_reason"),
        ]

    def __str__(self) -> str:
        return f"referral {self.pk} ({self.kind})"


@track_history()
class OrderSet(models.Model):
    """A reusable group of orders; ``owner`` set = a doctor's favorite (FEATURES 3.6)."""

    name_ar = models.CharField(max_length=150)
    name_en = models.CharField(max_length=150)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="order_sets",
        help_text="Empty = shared with every doctor.",
    )
    department = models.ForeignKey(
        "core.Department", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "order set"
        ordering: ClassVar[list[str]] = ["sort_order", "name_en"]

    def __str__(self) -> str:
        return self.name_en or self.name_ar


@track_history()
class OrderSetItem(models.Model):
    order_set = models.ForeignKey(OrderSet, on_delete=models.CASCADE, related_name="items")
    service = models.ForeignKey("catalog.Service", on_delete=models.PROTECT, related_name="+")
    quantity = quantity_field(default=1)
    dose = models.CharField(max_length=60, blank=True)
    frequency_code = models.CharField(max_length=20, blank=True)
    duration_days = models.PositiveSmallIntegerField(null=True, blank=True)
    instructions = models.CharField(max_length=300, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "order set item"
        ordering: ClassVar[list[str]] = ["order_set", "sort_order", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="clinical_orderset_qty_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.order_set_id}: {self.service_id}"


class NursingNoteKind(models.TextChoices):
    GENERAL = "general", "General"
    PROCEDURE = "procedure", "Procedure"
    HANDOVER = "handover", "Handover"


@track_history()
class NursingNote(models.Model):
    """Nursing note for a visit (FEATURES 10.3)."""

    visit = models.ForeignKey(
        "visits.Visit", on_delete=models.PROTECT, related_name="nursing_notes"
    )
    kind = models.CharField(
        max_length=20, choices=NursingNoteKind.choices, default=NursingNoteKind.GENERAL
    )
    service_line = models.ForeignKey(
        "orders.ServiceLine",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="nursing_notes",
    )
    text = models.TextField()
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "nursing note"
        ordering: ClassVar[list[str]] = ["visit", "created_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("kind", NursingNoteKind, "clinical_nursingnote_kind_valid"),
            models.CheckConstraint(condition=~Q(text=""), name="clinical_nursingnote_has_text"),
        ]

    def __str__(self) -> str:
        return f"nursing note {self.pk} visit {self.visit_id}"
