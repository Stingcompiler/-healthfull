"""Patient portal access codes (FEATURES 15.2, P2; schema only in Phase 1).

The code itself is never stored: ``code_hash`` holds a Django password hash of it. A code
expires, locks after ``max_attempts`` failed tries and can be revoked.
"""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.db import choice_check, track_history


class AccessPurpose(models.TextChoices):
    RESULTS = "results", "View approved results"
    RECEIPT = "receipt", "Verify a receipt"
    APPOINTMENTS = "appointments", "Appointments"


@track_history(exclude=["code_hash"])
class PortalAccessCode(models.Model):
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="portal_codes"
    )
    visit = models.ForeignKey(
        "visits.Visit", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    purpose = models.CharField(
        max_length=20, choices=AccessPurpose.choices, default=AccessPurpose.RESULTS
    )
    code_hash = models.CharField(max_length=256)
    expires_at = models.DateTimeField()
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    locked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "portal access code"
        ordering: ClassVar[list[str]] = ["-created_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("purpose", AccessPurpose, "portal_code_purpose_valid"),
            models.CheckConstraint(
                condition=Q(max_attempts__gte=1), name="portal_code_attempts_positive"
            ),
            models.CheckConstraint(
                condition=Q(failed_attempts__lte=F("max_attempts")),
                name="portal_code_attempts_within_max",
            ),
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("created_at")), name="portal_code_expires_later"
            ),
            models.CheckConstraint(condition=~Q(code_hash=""), name="portal_code_hash_required"),
            models.CheckConstraint(
                condition=Q(revoked_at__isnull=True) | Q(revoked_by__isnull=False),
                name="portal_code_revoke_documented",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["patient", "expires_at"], name="portal_code_patient_idx"),
        ]

    def __str__(self) -> str:
        return f"portal code {self.pk} for {self.patient_id}"
