"""The service line state machine and perform-first authorizations (ARCHITECTURE 4.4).

A ``ServiceLine`` is one ordered unit of service on a visit with two orthogonal statuses:

* ``billing_status``: ``unbilled`` -> ``invoiced`` -> ``settled``; ``credited`` (removed by a
  credit note). ``settled`` may fall back to ``invoiced`` when a transfer is rejected.
* ``fulfilment_status``: ``pending`` -> ``in_progress`` (optional) -> ``performed``; or
  ``cancelled``. ``performed`` and ``cancelled`` are terminal.

Database backstops (the domain and services check first, these catch bypasses):

* ``line_guard`` trigger: a line enters ``in_progress``/``performed`` only while settled or
  under an unrevoked ``PerformAuthorization`` of its own visit (invariant 1); a line starts
  unbilled and becomes invoiced/settled only once a frozen line of an approved invoice bills
  it; terminal fulfilment states never change (except the unbilled bed night of an
  admission cancelled in error, voided with it, ADR 0018); billing moves only along the
  arrows above; a billed line keeps its quantity, service, kind, payer and visit, and is
  cancelled only together with its credit; a line with dispensed units is never cancelled
  (its given units are performed and only the rest is closed); lines are never deleted
  (cancel them).
* ``authorization_guard`` trigger: an authorization's decision fields never change, a
  revocation is final, and authorizations are never deleted (invariant 4).
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
from apps.core.db import choice_check, quantity_field, track_history, truncate_guard

_AUTHORIZATION_GUARD_SQL = """
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'AUTHORIZATION_PERMANENT: authorization % is never deleted', OLD.id;
    END IF;
    IF NEW.visit_id IS DISTINCT FROM OLD.visit_id
       OR NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.reason_code_id IS DISTINCT FROM OLD.reason_code_id
       OR NEW.reason_note IS DISTINCT FROM OLD.reason_note
       OR NEW.approval_reference IS DISTINCT FROM OLD.approval_reference
       OR NEW.requested_by_id IS DISTINCT FROM OLD.requested_by_id
       OR NEW.authorized_by_id IS DISTINCT FROM OLD.authorized_by_id
       OR NEW.authorized_at IS DISTINCT FROM OLD.authorized_at THEN
        RAISE EXCEPTION 'AUTHORIZATION_READONLY: authorization % records a decision', OLD.id;
    END IF;
    IF OLD.revoked_at IS NOT NULL AND (
        NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
        OR NEW.revoked_by_id IS DISTINCT FROM OLD.revoked_by_id
        OR NEW.revoke_note IS DISTINCT FROM OLD.revoke_note) THEN
        RAISE EXCEPTION 'AUTHORIZATION_REVOKED: authorization % stays revoked', OLD.id;
    END IF;
    RETURN NEW;
"""


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
        triggers: ClassVar[list[pgtrigger.Trigger]] = [
            truncate_guard(),
            pgtrigger.Trigger(
                name="authorization_guard",
                when=pgtrigger.Before,
                operation=pgtrigger.Update | pgtrigger.Delete,
                func=_AUTHORIZATION_GUARD_SQL,
            ),
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
    IF TG_OP = 'INSERT' AND NEW.billing_status <> 'unbilled' THEN
        RAISE EXCEPTION 'LINE_BILLING_TRANSITION: service line % must start unbilled', NEW.id;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.fulfilment_status IN ('performed', 'cancelled')
           AND NEW.fulfilment_status IS DISTINCT FROM OLD.fulfilment_status
           AND NOT (
               -- ADR 0018: the one exception. An unbilled bed night of an admission
               -- cancelled in error is voided (nothing was billed: invariants 2 and 3).
               OLD.fulfilment_status = 'performed' AND NEW.fulfilment_status = 'cancelled'
               AND OLD.billing_status = 'unbilled' AND NEW.billing_status = 'unbilled'
               AND OLD.order_source = 'bed_charge'
               AND EXISTS (
                   SELECT 1 FROM visits_bedcharge bc
                     JOIN visits_admission a ON a.id = bc.admission_id
                    WHERE bc.service_line_id = OLD.id AND a.status = 'cancelled'
               )
           ) THEN
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
        -- Billed only from a frozen line of an approved invoice (invariant 1).
        IF OLD.billing_status = 'unbilled' AND NEW.billing_status <> 'unbilled'
           AND NOT EXISTS (
               SELECT 1 FROM billing_invoiceline il
                 JOIN billing_invoice i ON i.id = il.invoice_id
                WHERE il.service_line_id = NEW.id AND il.frozen AND i.status = 'approved'
           ) THEN
            RAISE EXCEPTION 'LINE_NOT_INVOICED: service line % is on no approved invoice',
                NEW.id;
        END IF;
        -- What was ordered and billed never changes afterwards.
        IF NEW.visit_id IS DISTINCT FROM OLD.visit_id
           OR (OLD.billing_status <> 'unbilled' AND (
               NEW.quantity IS DISTINCT FROM OLD.quantity
               OR NEW.service_id IS DISTINCT FROM OLD.service_id
               OR NEW.kind IS DISTINCT FROM OLD.kind
               OR NEW.payer_id IS DISTINCT FROM OLD.payer_id)) THEN
            RAISE EXCEPTION 'LINE_BILLED_READONLY: service line % is billed; its order is fixed',
                OLD.id;
        END IF;
        IF NEW.authorization_id IS DISTINCT FROM OLD.authorization_id
           AND OLD.authorization_id IS NOT NULL THEN
            RAISE EXCEPTION 'LINE_AUTHORIZATION_FIXED: service line % keeps its authorization',
                OLD.id;
        END IF;
        -- A billed line is cancelled only by the credit note that credits it (ARCH 4.4).
        IF NEW.fulfilment_status = 'cancelled' AND OLD.fulfilment_status <> 'cancelled'
           AND NEW.billing_status IN ('invoiced', 'settled') THEN
            RAISE EXCEPTION 'CREDIT_NOTE_REQUIRED: billed service line % needs a credit note',
                OLD.id;
        END IF;
        -- Stock that left for a line is never cancelled away: perform the given units and
        -- close the rest instead (invariants 1 and 5).
        IF NEW.fulfilment_status = 'cancelled' AND OLD.fulfilment_status <> 'cancelled'
           AND EXISTS (SELECT 1 FROM pharmacy_dispenseline d WHERE d.service_line_id = NEW.id)
        THEN
            RAISE EXCEPTION 'LINE_PARTLY_DISPENSED: service line % has dispensed units', OLD.id;
        END IF;
    END IF;
    IF NEW.fulfilment_status IN ('in_progress', 'performed')
       AND (TG_OP = 'INSERT' OR NEW.fulfilment_status IS DISTINCT FROM OLD.fulfilment_status)
       AND NEW.billing_status <> 'settled' THEN
        -- FOR SHARE: a concurrent revocation (which locks the authorization FOR UPDATE)
        -- either commits first and is seen here, or waits for this transaction.
        PERFORM 1 FROM orders_performauthorization a
         WHERE a.id = NEW.authorization_id AND a.revoked_at IS NULL
           AND a.visit_id = NEW.visit_id
           FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION
                'LINE_NOT_ELIGIBLE: service line % is neither settled nor authorized to perform',
                NEW.id;
        END IF;
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
            truncate_guard(),
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
