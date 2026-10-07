"""The service line state machine and perform-first authorizations (ARCHITECTURE 4.4).

A ``ServiceLine`` is one ordered unit of service on a visit with two orthogonal statuses:

* ``billing_status``: ``unbilled`` -> ``invoiced`` -> ``settled``; ``credited`` (removed by a
  credit note). ``settled`` may fall back to ``invoiced`` when a transfer is rejected.
* ``fulfilment_status``: ``pending`` -> ``in_progress`` (optional) -> ``performed``; or
  ``cancelled``. ``performed`` and ``cancelled`` are terminal.

Database backstops (the domain and services check first, these catch bypasses):

* ``line_guard`` trigger: a line enters ``in_progress``/``performed`` only while settled or
  under an unrevoked ``PerformAuthorization`` (invariant 1); terminal fulfilment states never
  change; billing moves only along the arrows above; lines are never deleted (cancel them).
* Check constraints: every cancellation records reason, actor and time (invariant 4), every
  performance records actor and time, invoiced/credited lines carry their timestamps.
"""

from __future__ import annotations

from typing import ClassVar

import pgtrigger
from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.catalog.models import ServiceKind
from apps.core.db import choice_check, quantity_field, track_history


class AuthorizationKind(models.TextChoices):
    INSURANCE_APPROVAL = "insurance_approval", "Insurance approval"
    EMERGENCY = "emergency", "Emergency"
    CREDIT_ACCOUNT = "credit_account", "Approved credit account"
    OTHER = "other", "Other"


@track_history()
class PerformAuthorization(models.Model):
    """A documented perform-first exception (FEATURES 4.4, invariant 1).

    Lines point at it through ``ServiceLine.authorization``. Revoking stops lines that have not
    started from entering work lists; it never undoes work already performed.
    """

    visit = models.ForeignKey(
        "visits.Visit", on_delete=models.PROTECT, related_name="perform_authorizations"
    )
    kind = models.CharField(max_length=30, choices=AuthorizationKind.choices)
    reason_code = models.ForeignKey(
        "core.ReasonCode",
        on_delete=models.PROTECT,
        related_name="+",
        limit_choices_to={"category": "perform_first"},
    )
    reason_note = models.TextField(blank=True)
    approval_reference = models.CharField(
        max_length=100, blank=True, help_text="Payer pre-approval or credit account reference."
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    authorized_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    revoke_note = models.TextField(blank=True)

    class Meta:
        verbose_name = "perform-first authorization"
        ordering: ClassVar[list[str]] = ["-authorized_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("kind", AuthorizationKind, "orders_authorization_kind_valid"),
            models.CheckConstraint(
                condition=Q(revoked_at__isnull=True) | Q(revoked_by__isnull=False),
                name="orders_authorization_revoke_documented",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["authorized_at"], name="orders_auth_time_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} on visit {self.visit_id}"


class BillingStatus(models.TextChoices):
    UNBILLED = "unbilled", "Not invoiced"
    INVOICED = "invoiced", "Invoiced"
    SETTLED = "settled", "Settled"
    CREDITED = "credited", "Credited"


class FulfilmentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    IN_PROGRESS = "in_progress", "In progress"
    PERFORMED = "performed", "Performed"
    CANCELLED = "cancelled", "Cancelled"


class OrderSource(models.TextChoices):
    CONSULTATION_FEE = "consultation_fee", "Consultation fee (automatic)"
    DOCTOR = "doctor", "Doctor order"
    RECEPTION = "reception", "Reception"
    NURSE = "nurse", "Nurse"
    BED_CHARGE = "bed_charge", "Daily bed charge"
    PHARMACY_SALE = "pharmacy_sale", "Walk-in pharmacy sale"


_LINE_GUARD_SQL = """
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'LINE_NOT_DELETABLE: service line % cannot be deleted; cancel it',
            OLD.id;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.fulfilment_status IN ('performed', 'cancelled')
           AND NEW.fulfilment_status IS DISTINCT FROM OLD.fulfilment_status THEN
            RAISE EXCEPTION 'LINE_TERMINAL: service line % is already %',
                OLD.id, OLD.fulfilment_status;
        END IF;
        IF NEW.billing_status IS DISTINCT FROM OLD.billing_status AND NOT (
            (OLD.billing_status = 'unbilled' AND NEW.billing_status IN ('invoiced', 'settled'))
            OR (OLD.billing_status = 'invoiced' AND NEW.billing_status IN ('settled', 'credited'))
            OR (OLD.billing_status = 'settled' AND NEW.billing_status IN ('invoiced', 'credited'))
        ) THEN
            RAISE EXCEPTION 'LINE_BILLING_TRANSITION: service line % cannot go from % to %',
                OLD.id, OLD.billing_status, NEW.billing_status;
        END IF;
    END IF;
    IF NEW.fulfilment_status IN ('in_progress', 'performed')
       AND (TG_OP = 'INSERT' OR NEW.fulfilment_status IS DISTINCT FROM OLD.fulfilment_status)
       AND NEW.billing_status <> 'settled'
       AND NOT EXISTS (
           SELECT 1 FROM orders_performauthorization a
           WHERE a.id = NEW.authorization_id AND a.revoked_at IS NULL
       ) THEN
        RAISE EXCEPTION
            'LINE_NOT_ELIGIBLE: service line % is neither settled nor authorized to perform',
            NEW.id;
    END IF;
    RETURN NEW;
"""


@track_history()
class ServiceLine(models.Model):
    visit = models.ForeignKey("visits.Visit", on_delete=models.PROTECT, related_name="lines")
    service = models.ForeignKey(
        "catalog.Service", on_delete=models.PROTECT, related_name="service_lines"
    )
    kind = models.CharField(
        max_length=20, choices=ServiceKind.choices, help_text="Copy of service.kind at order time."
    )
    department = models.ForeignKey(
        "core.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="service_lines",
        help_text="Performing department at order time.",
    )
    quantity = quantity_field(default=1)
    payer = models.ForeignKey(
        "catalog.Payer",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="service_lines",
        help_text="Payer this line will be billed to; empty = the patient pays (cash).",
    )
    pre_approval_ref = models.CharField(max_length=100, blank=True)
    order_source = models.CharField(
        max_length=20, choices=OrderSource.choices, default=OrderSource.DOCTOR
    )
    order_note = models.CharField(max_length=500, blank=True)
    ordered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    ordered_at = models.DateTimeField(auto_now_add=True)

    billing_status = models.CharField(
        max_length=20, choices=BillingStatus.choices, default=BillingStatus.UNBILLED
    )
    fulfilment_status = models.CharField(
        max_length=20, choices=FulfilmentStatus.choices, default=FulfilmentStatus.PENDING
    )
    authorization = models.ForeignKey(
        PerformAuthorization,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lines",
    )

    invoiced_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    credited_at = models.DateTimeField(null=True, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    performed_at = models.DateTimeField(null=True, blank=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    performed_quantity = quantity_field(
        null=True, blank=True, help_text="Quantity actually performed (partial dispense)."
    )
    performed_note = models.CharField(max_length=500, blank=True)

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    cancel_reason = models.ForeignKey(
        "core.ReasonCode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to={"category": "line_cancel"},
    )
    cancel_note = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "service line"
        ordering: ClassVar[list[str]] = ["visit", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("kind", ServiceKind, "orders_line_kind_valid"),
            choice_check("billing_status", BillingStatus, "orders_line_billing_valid"),
            choice_check("fulfilment_status", FulfilmentStatus, "orders_line_fulfilment_valid"),
            choice_check("order_source", OrderSource, "orders_line_source_valid"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="orders_line_qty_positive"),
            models.CheckConstraint(
                condition=Q(performed_quantity__isnull=True)
                | (Q(performed_quantity__gte=0) & Q(performed_quantity__lte=F("quantity"))),
                name="orders_line_performed_qty_range",
            ),
            models.CheckConstraint(
                condition=~Q(fulfilment_status=FulfilmentStatus.CANCELLED)
                | Q(
                    cancelled_at__isnull=False,
                    cancelled_by__isnull=False,
                    cancel_reason__isnull=False,
                ),
                name="orders_line_cancel_documented",
            ),
            models.CheckConstraint(
                condition=~Q(fulfilment_status=FulfilmentStatus.PERFORMED)
                | Q(performed_at__isnull=False, performed_by__isnull=False),
                name="orders_line_performed_documented",
            ),
            models.CheckConstraint(
                condition=~Q(fulfilment_status=FulfilmentStatus.IN_PROGRESS)
                | Q(started_at__isnull=False),
                name="orders_line_started_documented",
            ),
            models.CheckConstraint(
                condition=Q(billing_status=BillingStatus.UNBILLED) | Q(invoiced_at__isnull=False),
                name="orders_line_invoiced_has_time",
            ),
            models.CheckConstraint(
                condition=~Q(billing_status=BillingStatus.CREDITED) | Q(credited_at__isnull=False),
                name="orders_line_credited_has_time",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            # Work lists: open lines of one kind / department (FEATURES 4.3).
            models.Index(
                fields=["kind", "department", "billing_status"],
                condition=Q(fulfilment_status__in=["pending", "in_progress"]),
                name="orders_line_worklist_idx",
            ),
            # Requested-not-invoiced with age (FEATURES 4.5).
            models.Index(fields=["billing_status", "ordered_at"], name="orders_line_billing_idx"),
            models.Index(
                fields=["fulfilment_status", "performed_at"], name="orders_line_performed_idx"
            ),
        ]
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            pgtrigger.Trigger(
                name="line_guard",
                when=pgtrigger.Before,
                operation=pgtrigger.Insert | pgtrigger.Update | pgtrigger.Delete,
                func=_LINE_GUARD_SQL,
            ),
        ]

    def __str__(self) -> str:
        return f"line {self.pk} ({self.kind}) visit {self.visit_id}"


class Route(models.TextChoices):
    ORAL = "oral", "Oral"
    IV = "iv", "Intravenous"
    IM = "im", "Intramuscular"
    SC = "sc", "Subcutaneous"
    TOPICAL = "topical", "Topical"
    INHALED = "inhaled", "Inhaled"
    RECTAL = "rectal", "Rectal"
    OPHTHALMIC = "ophthalmic", "Eye"
    OTIC = "otic", "Ear"
    NASAL = "nasal", "Nasal"
    OTHER = "other", "Other"


@track_history()
class PrescriptionDetail(models.Model):
    """Dose, frequency and duration of a drug line (FEATURES 3.5).

    The line's ``quantity`` (base units) is computed from these by the domain at order time.
    """

    line = models.OneToOneField(ServiceLine, on_delete=models.CASCADE, related_name="prescription")
    dose = models.CharField(max_length=60, help_text="As written, e.g. '500 mg' or '1 tablet'.")
    dose_quantity = quantity_field(
        null=True, blank=True, help_text="Base units per dose, when computable."
    )
    route = models.CharField(max_length=20, choices=Route.choices, default=Route.ORAL)
    frequency_code = models.CharField(max_length=20, blank=True, help_text="e.g. OD, BID, TID.")
    frequency_per_day = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    duration_days = models.PositiveSmallIntegerField(null=True, blank=True)
    as_needed = models.BooleanField(default=False)
    instructions = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = "prescription detail"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("route", Route, "orders_prescription_route_valid"),
            models.CheckConstraint(
                condition=Q(dose_quantity__isnull=True) | Q(dose_quantity__gt=0),
                name="orders_prescription_dose_positive",
            ),
            models.CheckConstraint(
                condition=Q(frequency_per_day__isnull=True) | Q(frequency_per_day__gt=0),
                name="orders_prescription_frequency_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.dose} {self.frequency_code}".strip()
