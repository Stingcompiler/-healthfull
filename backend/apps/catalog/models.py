"""Service catalog, price lists, payers and coverage rules (FEATURES 5.1-5.8, 11.1).

Prices are looked up from the ``PriceListVersion`` effective on the invoice approval date for
the line's payer price list (cash list when the payer has none) and frozen on the invoice
line (invariant 6). Coverage per line comes from the most specific active ``CoverageRule``
(service, then service kind, then payer default); an ``Exclusion`` routes the line 100% to the
patient (ARCHITECTURE 4.5, ``domain/coverage.py``).
"""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import F, Q

from apps.core.db import choice_check, money_field, percent_field, track_history


class ServiceKind(models.TextChoices):
    CONSULTATION = "consultation", "Consultation"
    LAB = "lab", "Laboratory test"
    PROCEDURE = "procedure", "Procedure"
    DRUG = "drug", "Drug"
    CONSUMABLE = "consumable", "Consumable"
    BED = "bed", "Bed day"


@track_history()
class ServiceCategory(models.Model):
    """Grouping for the catalog screens and reports (FEATURES 5.1)."""

    code = models.CharField(max_length=30, unique=True)
    name_ar = models.CharField(max_length=150)
    name_en = models.CharField(max_length=150)
    sort_order = models.PositiveSmallIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "service category"
        verbose_name_plural = "service categories"
        ordering: ClassVar[list[str]] = ["sort_order", "code"]

    def __str__(self) -> str:
        return self.name_en or self.code


@track_history()
class Service(models.Model):
    """Anything that can become a service line: consultation, test, procedure, drug, ..."""

    code = models.CharField(max_length=40, unique=True)
    name_ar = models.CharField(max_length=200)
    name_en = models.CharField(max_length=200)
    kind = models.CharField(max_length=20, choices=ServiceKind.choices, db_index=True)
    department = models.ForeignKey(
        "core.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="services",
        help_text="Performing department (revenue dimension).",
    )
    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="services",
    )
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "service"
        ordering: ClassVar[list[str]] = ["kind", "sort_order", "code"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("kind", ServiceKind, "catalog_service_kind_valid"),
            models.CheckConstraint(
                condition=~Q(name_ar="") | ~Q(name_en=""), name="catalog_service_has_name"
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["kind", "active"], name="catalog_service_kind_idx"),
            GinIndex(
                fields=["name_ar"], opclasses=["gin_trgm_ops"], name="catalog_service_name_ar_trgm"
            ),
            GinIndex(
                fields=["name_en"], opclasses=["gin_trgm_ops"], name="catalog_service_name_en_trgm"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.name_en or self.name_ar}"


# --- Price lists ---------------------------------------------------------------------------


class PriceListKind(models.TextChoices):
    CASH = "cash", "Cash (self-pay)"
    PAYER = "payer", "Payer contract"


@track_history()
class PriceList(models.Model):
    """A named list of prices (cash, or one per payer contract). Prices live in versions."""

    code = models.CharField(max_length=30, unique=True)
    name_ar = models.CharField(max_length=150)
    name_en = models.CharField(max_length=150)
    kind = models.CharField(
        max_length=10, choices=PriceListKind.choices, default=PriceListKind.CASH
    )
    is_default = models.BooleanField(
        default=False, help_text="The cash list used when a line has no payer list."
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "price list"
        ordering: ClassVar[list[str]] = ["code"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("kind", PriceListKind, "catalog_pricelist_kind_valid"),
            models.UniqueConstraint(
                fields=["is_default"],
                condition=Q(is_default=True),
                name="catalog_pricelist_one_default",
            ),
            models.CheckConstraint(
                condition=Q(is_default=False) | Q(kind=PriceListKind.CASH, active=True),
                name="catalog_pricelist_default_is_active_cash",
            ),
        ]

    def __str__(self) -> str:
        return self.name_en or self.code


@track_history()
class PriceListVersion(models.Model):
    """Prices of one list from ``effective_from`` until the next version (FEATURES 5.2).

    A bulk percentage update creates a new dated version from ``based_on``.
    """

    price_list = models.ForeignKey(PriceList, on_delete=models.PROTECT, related_name="versions")
    effective_from = models.DateField()
    based_on = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="derived_versions"
    )
    percent_change = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Bulk change applied to based_on, e.g. 15.00 for +15%.",
    )
    note = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "price list version"
        ordering: ClassVar[list[str]] = ["price_list", "-effective_from"]
        get_latest_by = "effective_from"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["price_list", "effective_from"], name="catalog_pricelistversion_unique"
            ),
            models.CheckConstraint(
                condition=Q(percent_change__isnull=True) | Q(percent_change__gt=-100),
                name="catalog_pricelistversion_percent_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.price_list_id} from {self.effective_from}"


@track_history()
class PriceItem(models.Model):
    version = models.ForeignKey(PriceListVersion, on_delete=models.CASCADE, related_name="items")
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="price_items")
    unit_price = money_field()

    class Meta:
        verbose_name = "price item"
        ordering: ClassVar[list[str]] = ["version", "service"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["version", "service"], name="catalog_priceitem_unique"),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0), name="catalog_priceitem_price_non_negative"
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["service", "version"], name="catalog_priceitem_service_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.service_id} @ {self.unit_price}"


# --- Payers and coverage -------------------------------------------------------------------


class PayerKind(models.TextChoices):
    INSURANCE = "insurance", "Insurance company"
    COMPANY = "company", "Employer or company"
    GOVERNMENT = "government", "Government scheme"
    NGO = "ngo", "NGO or charity"
    OTHER = "other", "Other"


class ClaimPeriod(models.TextChoices):
    WEEKLY = "weekly", "Weekly"
    BIWEEKLY = "biweekly", "Every two weeks"
    MONTHLY = "monthly", "Monthly"
    QUARTERLY = "quarterly", "Quarterly"


@track_history()
class Payer(models.Model):
    """Insurance company or other third party that pays part of a bill (FEATURES 11.1).

    The payer share of a line is a receivable (AR_PAYER) until a payer payment is recorded
    (invariant 7).
    """

    code = models.CharField(max_length=30, unique=True)
    name_ar = models.CharField(max_length=200)
    name_en = models.CharField(max_length=200)
    kind = models.CharField(max_length=20, choices=PayerKind.choices, default=PayerKind.INSURANCE)
    price_list = models.ForeignKey(
        PriceList,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payers",
        help_text="Contract price list; the default cash list when empty.",
    )
    contract_no = models.CharField(max_length=100, blank=True)
    contract_start = models.DateField(null=True, blank=True)
    contract_end = models.DateField(null=True, blank=True)
    claim_period = models.CharField(
        max_length=20, choices=ClaimPeriod.choices, default=ClaimPeriod.MONTHLY
    )
    requires_card_number = models.BooleanField(default=True)
    contact_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=300, blank=True)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "payer"
        ordering: ClassVar[list[str]] = ["code"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("kind", PayerKind, "catalog_payer_kind_valid"),
            choice_check("claim_period", ClaimPeriod, "catalog_payer_claim_period_valid"),
            models.CheckConstraint(
                condition=Q(contract_start__isnull=True)
                | Q(contract_end__isnull=True)
                | Q(contract_end__gte=F("contract_start")),
                name="catalog_payer_contract_dates",
            ),
        ]

    def __str__(self) -> str:
        return self.name_en or self.code


class CoverageRuleKind(models.TextChoices):
    PERCENTAGE = "percentage", "Payer pays a percentage"
    COPAY = "copay", "Patient pays a fixed copay"
    CEILING = "ceiling", "Payer pays up to a ceiling"


@track_history()
class CoverageRule(models.Model):
    """How a payer shares a line with the patient (FEATURES 5.5).

    Scope, most specific first: ``service``; else ``service_kind``; else neither (the payer's
    default rule). At most one active rule per scope.

    * ``percentage``: payer pays ``payer_percent`` of the net line.
    * ``copay``: patient pays ``copay_amount`` (capped at the line), payer the rest.
    * ``ceiling``: payer pays ``payer_percent`` (default 100) up to ``ceiling_amount``.
    """

    payer = models.ForeignKey(Payer, on_delete=models.CASCADE, related_name="coverage_rules")
    service = models.ForeignKey(
        Service, on_delete=models.CASCADE, null=True, blank=True, related_name="coverage_rules"
    )
    service_kind = models.CharField(max_length=20, choices=ServiceKind.choices, blank=True)
    rule_kind = models.CharField(max_length=20, choices=CoverageRuleKind.choices)
    payer_percent = percent_field(null=True, blank=True)
    copay_amount = money_field(null=True, blank=True)
    ceiling_amount = money_field(null=True, blank=True)
    requires_pre_approval = models.BooleanField(
        default=False, help_text="The line needs a payer pre-approval reference (FEATURES 5.8)."
    )
    active = models.BooleanField(default=True)
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "coverage rule"
        ordering: ClassVar[list[str]] = ["payer", "service", "service_kind"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            choice_check("rule_kind", CoverageRuleKind, "catalog_coveragerule_kind_valid"),
            models.CheckConstraint(
                condition=Q(service_kind="") | Q(service_kind__in=ServiceKind.values),
                name="catalog_coveragerule_service_kind_valid",
            ),
            models.CheckConstraint(
                condition=Q(service__isnull=True) | Q(service_kind=""),
                name="catalog_coveragerule_one_scope",
            ),
            models.CheckConstraint(
                condition=Q(payer_percent__isnull=True)
                | (Q(payer_percent__gte=0) & Q(payer_percent__lte=100)),
                name="catalog_coveragerule_percent_range",
            ),
            models.CheckConstraint(
                condition=(Q(copay_amount__isnull=True) | Q(copay_amount__gte=0))
                & (Q(ceiling_amount__isnull=True) | Q(ceiling_amount__gte=0)),
                name="catalog_coveragerule_amounts_non_negative",
            ),
            models.CheckConstraint(
                condition=~Q(rule_kind=CoverageRuleKind.PERCENTAGE)
                | Q(payer_percent__isnull=False),
                name="catalog_coveragerule_percentage_needs_percent",
            ),
            models.CheckConstraint(
                condition=~Q(rule_kind=CoverageRuleKind.COPAY) | Q(copay_amount__isnull=False),
                name="catalog_coveragerule_copay_needs_amount",
            ),
            models.CheckConstraint(
                condition=~Q(rule_kind=CoverageRuleKind.CEILING) | Q(ceiling_amount__isnull=False),
                name="catalog_coveragerule_ceiling_needs_amount",
            ),
            models.UniqueConstraint(
                fields=["payer", "service"],
                condition=Q(active=True, service__isnull=False),
                name="catalog_coveragerule_one_per_service",
            ),
            models.UniqueConstraint(
                fields=["payer", "service_kind"],
                condition=Q(active=True, service__isnull=True) & ~Q(service_kind=""),
                name="catalog_coveragerule_one_per_kind",
            ),
            models.UniqueConstraint(
                fields=["payer"],
                condition=Q(active=True, service__isnull=True, service_kind=""),
                name="catalog_coveragerule_one_default",
            ),
        ]

    def __str__(self) -> str:
        scope = self.service_id or self.service_kind or "default"
        return f"{self.payer_id}/{scope}: {self.rule_kind}"


@track_history()
class Exclusion(models.Model):
    """A service (or a whole kind) the payer never covers: 100% to the patient (FEATURES 5.7)."""

    payer = models.ForeignKey(Payer, on_delete=models.CASCADE, related_name="exclusions")
    service = models.ForeignKey(
        Service, on_delete=models.CASCADE, null=True, blank=True, related_name="exclusions"
    )
    service_kind = models.CharField(max_length=20, choices=ServiceKind.choices, blank=True)
    note = models.CharField(max_length=300, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "coverage exclusion"
        ordering: ClassVar[list[str]] = ["payer", "service", "service_kind"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(service_kind="") | Q(service_kind__in=ServiceKind.values),
                name="catalog_exclusion_service_kind_valid",
            ),
            models.CheckConstraint(
                condition=(Q(service__isnull=False) & Q(service_kind=""))
                | (Q(service__isnull=True) & ~Q(service_kind="")),
                name="catalog_exclusion_exactly_one_scope",
            ),
            models.UniqueConstraint(
                fields=["payer", "service"],
                condition=Q(service__isnull=False),
                name="catalog_exclusion_unique_service",
            ),
            models.UniqueConstraint(
                fields=["payer", "service_kind"],
                condition=Q(service__isnull=True),
                name="catalog_exclusion_unique_kind",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.payer_id} excludes {self.service_id or self.service_kind}"
