"""Laboratory: test catalog, samples, versioned results (FEATURES 9).

A ``ResultSet`` belongs to one ordered lab service line. Results are entered into a ``draft``
``ResultVersion``; a lab supervisor approves it, which performs the line. A correction after
approval is a new version that ``amends`` the previous one; when it is approved the previous
version becomes ``amended`` (superseded). Only approved versions are visible to doctors and
patients.

Database backstops: an approved version can only move to ``amended`` (changing nothing else
but the supersession stamp); an amended version never changes; versions are never deleted
once approved; values can be written only while their version is a draft. At most one draft
and one approved version exist per result set, so an amendment marks the previous version
``amended`` before approving the new one (same transaction).
"""

from __future__ import annotations

from typing import ClassVar

import pgtrigger
from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.db import choice_check, parent_must_be_editable, track_history, truncate_guard


class SampleType(models.TextChoices):
    WHOLE_BLOOD = "whole_blood", "Whole blood"
    SERUM = "serum", "Serum"
    PLASMA = "plasma", "Plasma"
    URINE = "urine", "Urine"
    STOOL = "stool", "Stool"
    SWAB = "swab", "Swab"
    SPUTUM = "sputum", "Sputum"
    CSF = "csf", "Cerebrospinal fluid"
    FLUID = "fluid", "Other body fluid"
    OTHER = "other", "Other"


@track_history()
class LabTest(models.Model):
    """An orderable test or panel (FEATURES 9.1), one per catalog service of kind lab."""

    service = models.OneToOneField(
        "catalog.Service", on_delete=models.PROTECT, related_name="lab_test"
    )
    code = models.CharField(max_length=30, unique=True)
    sample_type = models.CharField(max_length=20, choices=SampleType.choices)
    container = models.CharField(max_length=60, blank=True, help_text="e.g. EDTA, plain tube.")
    method = models.CharField(max_length=100, blank=True)
    turnaround_minutes = models.PositiveIntegerField(default=60)
    instructions_ar = models.CharField(max_length=300, blank=True)
    instructions_en = models.CharField(max_length=300, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "lab test"
        ordering: ClassVar[list[str]] = ["sort_order", "code"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("sample_type", SampleType, "lab_test_sample_type_valid"),
            models.CheckConstraint(
                condition=Q(turnaround_minutes__gte=1), name="lab_test_turnaround_positive"
            ),
        ]

    def __str__(self) -> str:
        return self.code


class ValueType(models.TextChoices):
    NUMERIC = "numeric", "Number"
    TEXT = "text", "Free text"
    CHOICE = "choice", "One of a list"
    POS_NEG = "pos_neg", "Positive / negative"


@track_history()
class LabParameter(models.Model):
    test = models.ForeignKey(LabTest, on_delete=models.CASCADE, related_name="parameters")
    code = models.CharField(max_length=30)
    name_ar = models.CharField(max_length=150)
    name_en = models.CharField(max_length=150)
    unit = models.CharField(max_length=30, blank=True)
    value_type = models.CharField(
        max_length=20, choices=ValueType.choices, default=ValueType.NUMERIC
    )
    choices = models.JSONField(default=list, blank=True, help_text="Allowed values for 'choice'.")
    decimals = models.PositiveSmallIntegerField(default=1)
    sort_order = models.PositiveSmallIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "lab parameter"
        ordering: ClassVar[list[str]] = ["test", "sort_order", "code"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("value_type", ValueType, "lab_parameter_value_type_valid"),
            models.UniqueConstraint(fields=["test", "code"], name="lab_parameter_unique"),
            models.CheckConstraint(condition=Q(decimals__lte=6), name="lab_parameter_decimals"),
        ]

    def __str__(self) -> str:
        return f"{self.test_id}/{self.code}"


class RangeSex(models.TextChoices):
    ANY = "any", "Any"
    MALE = "male", "Male"
    FEMALE = "female", "Female"


@track_history()
class ReferenceRange(models.Model):
    """Normal and critical limits by sex and age in days (FEATURES 9.1, 9.3)."""

    parameter = models.ForeignKey(
        LabParameter, on_delete=models.CASCADE, related_name="reference_ranges"
    )
    sex = models.CharField(max_length=10, choices=RangeSex.choices, default=RangeSex.ANY)
    age_min_days = models.PositiveIntegerField(default=0)
    age_max_days = models.PositiveIntegerField(null=True, blank=True)
    low = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    high = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    critical_low = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    critical_high = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    normal_text = models.CharField(
        max_length=100, blank=True, help_text="Normal value for text/choice parameters."
    )
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "reference range"
        ordering: ClassVar[list[str]] = ["parameter", "sex", "age_min_days"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("sex", RangeSex, "lab_range_sex_valid"),
            models.CheckConstraint(
                condition=Q(age_max_days__isnull=True) | Q(age_max_days__gte=F("age_min_days")),
                name="lab_range_age_order",
            ),
            models.CheckConstraint(
                condition=Q(low__isnull=True) | Q(high__isnull=True) | Q(high__gte=F("low")),
                name="lab_range_low_le_high",
            ),
            models.CheckConstraint(
                condition=Q(critical_low__isnull=True)
                | Q(low__isnull=True)
                | Q(critical_low__lte=F("low")),
                name="lab_range_critical_low_below_low",
            ),
            models.CheckConstraint(
                condition=Q(critical_high__isnull=True)
                | Q(high__isnull=True)
                | Q(critical_high__gte=F("high")),
                name="lab_range_critical_high_above_high",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.parameter_id} {self.sex} {self.low}-{self.high}"


class SampleStatus(models.TextChoices):
    COLLECTED = "collected", "Collected"
    RECEIVED = "received", "Received in lab"
    REJECTED = "rejected", "Rejected"


@track_history()
class Sample(models.Model):
    """A specimen; one sample may serve several tests of the same visit (FEATURES 9.2)."""

    accession_no = models.CharField(max_length=30, unique=True)
    visit = models.ForeignKey("visits.Visit", on_delete=models.PROTECT, related_name="samples")
    sample_type = models.CharField(max_length=20, choices=SampleType.choices)
    status = models.CharField(
        max_length=20, choices=SampleStatus.choices, default=SampleStatus.COLLECTED
    )
    collected_at = models.DateTimeField()
    collected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    received_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    rejection_reason = models.ForeignKey(
        "core.ReasonCode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to={"category": "sample_reject"},
    )
    rejection_note = models.CharField(max_length=300, blank=True)
    label_printed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "sample"
        ordering: ClassVar[list[str]] = ["-collected_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("sample_type", SampleType, "lab_sample_type_valid"),
            choice_check("status", SampleStatus, "lab_sample_status_valid"),
            models.CheckConstraint(
                condition=~Q(status=SampleStatus.RECEIVED)
                | Q(received_at__isnull=False, received_by__isnull=False),
                name="lab_sample_receipt_documented",
            ),
            models.CheckConstraint(
                condition=~Q(status=SampleStatus.REJECTED) | Q(rejection_reason__isnull=False),
                name="lab_sample_rejection_has_reason",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["visit"], name="lab_sample_visit_idx"),
            models.Index(fields=["status", "collected_at"], name="lab_sample_status_idx"),
        ]

    def __str__(self) -> str:
        return self.accession_no


@track_history()
class ResultSet(models.Model):
    """The results of one ordered lab line, across its versions."""

    service_line = models.OneToOneField(
        "orders.ServiceLine", on_delete=models.PROTECT, related_name="result_set"
    )
    test = models.ForeignKey(LabTest, on_delete=models.PROTECT, related_name="result_sets")
    sample = models.ForeignKey(
        Sample, on_delete=models.PROTECT, null=True, blank=True, related_name="result_sets"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    first_approved_at = models.DateTimeField(
        null=True, blank=True, help_text="Turnaround time end (FEATURES 9.8)."
    )

    class Meta:
        verbose_name = "result set"
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["test", "first_approved_at"], name="lab_resultset_tat_idx"),
        ]

    def __str__(self) -> str:
        return f"results of line {self.service_line_id}"


class ResultStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    APPROVED = "approved", "Approved"
    AMENDED = "amended", "Amended (superseded)"


_RESULT_VERSION_GUARD_SQL = """
    IF OLD.status = 'amended' THEN
        RAISE EXCEPTION 'RESULT_FROZEN: amended result version % never changes (operation %)',
            OLD.id, TG_OP;
    END IF;
    IF OLD.status = 'approved' THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'RESULT_FROZEN: approved result version % cannot be deleted', OLD.id;
        END IF;
        IF NEW.status <> 'amended'
           OR NEW.superseded_at IS NULL OR NEW.superseded_by_id IS NULL
           OR (to_jsonb(NEW) - ARRAY['status', 'superseded_at', 'superseded_by_id'])
              IS DISTINCT FROM
              (to_jsonb(OLD) - ARRAY['status', 'superseded_at', 'superseded_by_id']) THEN
            RAISE EXCEPTION
                'RESULT_FROZEN: approved result version % can only be marked amended', OLD.id;
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
"""


@track_history()
class ResultVersion(models.Model):
    result_set = models.ForeignKey(ResultSet, on_delete=models.PROTECT, related_name="versions")
    version_no = models.PositiveSmallIntegerField()
    status = models.CharField(
        max_length=10, choices=ResultStatus.choices, default=ResultStatus.DRAFT
    )
    amends = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="amended_by"
    )
    amendment_reason = models.ForeignKey(
        "core.ReasonCode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to={"category": "result_amend"},
    )
    amendment_note = models.TextField(blank=True)
    comment = models.TextField(blank=True)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    entered_at = models.DateTimeField(auto_now_add=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    superseded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "result version"
        ordering: ClassVar[list[str]] = ["result_set", "version_no"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("status", ResultStatus, "lab_version_status_valid"),
            models.UniqueConstraint(
                fields=["result_set", "version_no"], name="lab_version_number_unique"
            ),
            models.UniqueConstraint(
                fields=["result_set"],
                condition=Q(status=ResultStatus.DRAFT),
                name="lab_version_one_draft",
            ),
            models.UniqueConstraint(
                fields=["result_set"],
                condition=Q(status=ResultStatus.APPROVED),
                name="lab_version_one_current",
            ),
            models.CheckConstraint(
                condition=Q(version_no__gte=1), name="lab_version_number_positive"
            ),
            models.CheckConstraint(
                condition=Q(status=ResultStatus.DRAFT)
                | Q(approved_by__isnull=False, approved_at__isnull=False),
                name="lab_version_approval_documented",
            ),
            models.CheckConstraint(
                condition=~Q(status=ResultStatus.AMENDED)
                | Q(superseded_at__isnull=False, superseded_by__isnull=False),
                name="lab_version_supersession_documented",
            ),
            models.CheckConstraint(
                condition=Q(amends__isnull=True) | Q(amendment_reason__isnull=False),
                name="lab_version_amendment_has_reason",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "approved_at"], name="lab_version_status_idx"),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            truncate_guard(),
            pgtrigger.Trigger(
                name="result_version_guard",
                when=pgtrigger.Before,
                operation=pgtrigger.Update | pgtrigger.Delete,
                condition=pgtrigger.Q(old__status__in=["approved", "amended"]),
                func=_RESULT_VERSION_GUARD_SQL,
            ),
        ]

    def __str__(self) -> str:
        return f"{self.result_set_id} v{self.version_no} ({self.status})"


class ResultFlag(models.TextChoices):
    NORMAL = "normal", "Normal"
    LOW = "low", "Low"
    HIGH = "high", "High"
    CRITICAL_LOW = "critical_low", "Critically low"
    CRITICAL_HIGH = "critical_high", "Critically high"
    ABNORMAL = "abnormal", "Abnormal"
    NONE = "none", "No range"


@track_history()
class ResultValue(models.Model):
    """One parameter's value in a version, with the range and flag it was judged against."""

    version = models.ForeignKey(ResultVersion, on_delete=models.CASCADE, related_name="values")
    parameter = models.ForeignKey(LabParameter, on_delete=models.PROTECT, related_name="+")
    value_numeric = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    value_text = models.CharField(max_length=500, blank=True)
    unit = models.CharField(max_length=30, blank=True)
    reference_low = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    reference_high = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    reference_text = models.CharField(max_length=100, blank=True)
    flag = models.CharField(max_length=20, choices=ResultFlag.choices, default=ResultFlag.NONE)

    class Meta:
        verbose_name = "result value"
        ordering: ClassVar[list[str]] = ["version", "parameter"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("flag", ResultFlag, "lab_value_flag_valid"),
            models.UniqueConstraint(fields=["version", "parameter"], name="lab_value_unique"),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            truncate_guard(),
            parent_must_be_editable(
                "value_needs_draft_version",
                code="RESULT_FROZEN",
                parent_table="lab_resultversion",
                fk_column="version_id",
                editable_condition="p.status = 'draft'",
            ),
        ]

    def __str__(self) -> str:
        shown = self.value_text if self.value_numeric is None else self.value_numeric
        return f"{self.parameter_id}={shown}"
