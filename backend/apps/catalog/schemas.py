"""Schemas of ``/api/catalog`` (FEATURES 5.1, 5.2, 11.1).

Money is a decimal string with two places (``"10000.00"``, ARCHITECTURE 4.3); amounts sent by
the client are strings too and are parsed strictly by ``domain.money.money`` in the router.
Prices are only in the price list schemas (``catalog.view_prices``); ``ServiceOut`` carries
none, so roles that may see the catalog but not prices (doctors) never receive them.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, ClassVar, Literal

from ninja import Field, Schema

from apps.core.schemas import PatchSchema
from domain.money import money

ServiceKindCode = Literal["consultation", "lab", "procedure", "drug", "consumable", "bed"]
PriceListKindCode = Literal["cash", "payer"]
PayerKindCode = Literal["insurance", "company", "government", "ngo", "other"]
ClaimPeriodCode = Literal["weekly", "biweekly", "monthly", "quarterly"]
RuleKindCode = Literal["percentage", "copay", "ceiling"]
VersionStatusCode = Literal["past", "current", "scheduled"]
RoundModeCode = Literal["half_up", "up", "down"]

#: A money amount as the API sends it: two decimal places, e.g. "15000.00".
MoneyStr = Annotated[str, Field(pattern=r"^-?[0-9]+\.[0-9]{2}$", examples=["15000.00"])]
#: A money amount sent by the client: digits with an optional decimal part (Arabic-Indic too).
MoneyIn = Annotated[str, Field(min_length=1, max_length=20, examples=["15000", "2500.50"])]
#: A percentage sent by the client, e.g. "10" or "-5.5" (two decimals at most).
PercentIn = Annotated[str, Field(min_length=1, max_length=10, examples=["10", "-5.5"])]

SERVICE_CODE = r"^[A-Z0-9][A-Z0-9_.-]{0,39}$"
LIST_CODE = r"^[A-Z][A-Z0-9_-]{0,29}$"


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(money(value))


def _pct(value: Decimal | None) -> str | None:
    return None if value is None else f"{Decimal(value):.2f}"


# --- Services and categories --------------------------------------------------------------


class ServiceOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str
    kind: ServiceKindCode
    department_id: int | None
    department_code: str | None
    category_id: int | None
    category_code: str | None
    description: str
    active: bool
    sort_order: int

    @staticmethod
    def resolve_department_code(obj: Any) -> str | None:
        return obj.department.code if obj.department_id else None

    @staticmethod
    def resolve_category_code(obj: Any) -> str | None:
        return obj.category.code if obj.category_id else None


class ServiceIn(Schema):
    code: str = Field(..., pattern=SERVICE_CODE)
    name_ar: str = Field("", max_length=200)
    name_en: str = Field("", max_length=200)
    kind: ServiceKindCode
    department_id: int | None = None
    category_id: int | None = None
    description: str = Field("", max_length=2000)
    active: bool = True
    sort_order: int = Field(0, ge=0, le=2_000_000_000)


class ServicePatch(PatchSchema):
    NULLABLE: ClassVar[frozenset[str]] = frozenset({"department_id", "category_id"})

    name_ar: str | None = Field(None, max_length=200)
    name_en: str | None = Field(None, max_length=200)
    department_id: int | None = None
    category_id: int | None = None
    description: str | None = Field(None, max_length=2000)
    active: bool | None = None
    sort_order: int | None = Field(None, ge=0, le=2_000_000_000)


class ServiceListParams(Schema):
    page: int = Field(1, ge=1)
    page_size: int = Field(25, ge=1, le=100)
    q: str | None = Field(None, max_length=200)
    kind: ServiceKindCode | None = None
    department_id: int | None = None
    category_id: int | None = None
    active: bool | None = None


class CategoryOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str
    sort_order: int
    active: bool


class CategoryIn(Schema):
    code: str = Field(..., pattern=LIST_CODE)
    name_ar: str = Field(..., min_length=1, max_length=150)
    name_en: str = Field(..., min_length=1, max_length=150)
    sort_order: int = Field(0, ge=0, le=32767)


class CategoryPatch(PatchSchema):
    name_ar: str | None = Field(None, min_length=1, max_length=150)
    name_en: str | None = Field(None, min_length=1, max_length=150)
    sort_order: int | None = Field(None, ge=0, le=32767)
    active: bool | None = None


class ActiveParams(Schema):
    active: bool | None = None


# --- Price lists and versions -------------------------------------------------------------


class VersionOut(Schema):
    """One version on a price list's timeline (built from ``services.VersionRow``)."""

    id: int
    price_list_id: int
    effective_from: date
    status: VersionStatusCode
    editable: bool = Field(..., description="Prices change only before the version starts")
    item_count: int
    based_on_id: int | None
    based_on_effective_from: date | None
    percent_change: str | None = Field(..., description="Bulk change on based_on, e.g. 10.00")
    note: str
    created_by: str | None
    created_at: datetime

    @staticmethod
    def resolve_id(obj: Any) -> int:
        return int(obj.version.pk)

    @staticmethod
    def resolve_price_list_id(obj: Any) -> int:
        return int(obj.version.price_list_id)

    @staticmethod
    def resolve_effective_from(obj: Any) -> date:
        return obj.version.effective_from

    @staticmethod
    def resolve_based_on_id(obj: Any) -> int | None:
        return obj.version.based_on_id

    @staticmethod
    def resolve_based_on_effective_from(obj: Any) -> date | None:
        base = obj.version.based_on
        return base.effective_from if base is not None else None

    @staticmethod
    def resolve_percent_change(obj: Any) -> str | None:
        return _pct(obj.version.percent_change)

    @staticmethod
    def resolve_note(obj: Any) -> str:
        return str(obj.version.note)

    @staticmethod
    def resolve_created_by(obj: Any) -> str | None:
        user = obj.version.created_by
        return user.username if user is not None else None

    @staticmethod
    def resolve_created_at(obj: Any) -> datetime:
        return obj.version.created_at


class PriceListOut(Schema):
    """A price list with its version timeline, newest first (``services.PriceListRow``)."""

    id: int
    code: str
    name_ar: str
    name_en: str
    kind: PriceListKindCode
    is_default: bool
    active: bool
    payer_codes: list[str]
    current_version_id: int | None
    next_version_id: int | None
    versions: list[VersionOut]

    @staticmethod
    def resolve_id(obj: Any) -> int:
        return int(obj.price_list.pk)

    @staticmethod
    def resolve_code(obj: Any) -> str:
        return str(obj.price_list.code)

    @staticmethod
    def resolve_name_ar(obj: Any) -> str:
        return str(obj.price_list.name_ar)

    @staticmethod
    def resolve_name_en(obj: Any) -> str:
        return str(obj.price_list.name_en)

    @staticmethod
    def resolve_kind(obj: Any) -> str:
        return str(obj.price_list.kind)

    @staticmethod
    def resolve_is_default(obj: Any) -> bool:
        return bool(obj.price_list.is_default)

    @staticmethod
    def resolve_active(obj: Any) -> bool:
        return bool(obj.price_list.active)

    @staticmethod
    def resolve_payer_codes(obj: Any) -> list[str]:
        return list(obj.payer_codes)

    @staticmethod
    def resolve_current_version_id(obj: Any) -> int | None:
        return obj.current.version.pk if obj.current is not None else None

    @staticmethod
    def resolve_next_version_id(obj: Any) -> int | None:
        nxt = obj.next_scheduled
        return nxt.version.pk if nxt is not None else None

    @staticmethod
    def resolve_versions(obj: Any) -> list[Any]:
        return list(obj.versions)


class PriceListIn(Schema):
    code: str = Field(..., pattern=LIST_CODE)
    name_ar: str = Field(..., min_length=1, max_length=150)
    name_en: str = Field(..., min_length=1, max_length=150)
    kind: PriceListKindCode = "payer"


class PriceListPatch(PatchSchema):
    name_ar: str | None = Field(None, min_length=1, max_length=150)
    name_en: str | None = Field(None, min_length=1, max_length=150)
    active: bool | None = None


class VersionIn(Schema):
    effective_from: date = Field(..., description="Tomorrow at the earliest (today for a first)")
    copy_from_id: int | None = Field(
        None,
        description="Version (of any list) to copy; default: this list's version effective then",
    )
    note: str = Field("", max_length=300)


class PriceItemOut(Schema):
    service_id: int
    service_code: str
    service_name_ar: str
    service_name_en: str
    service_kind: ServiceKindCode
    service_active: bool
    unit_price: MoneyStr

    @staticmethod
    def resolve_service_code(obj: Any) -> str:
        return str(obj.service.code)

    @staticmethod
    def resolve_service_name_ar(obj: Any) -> str:
        return str(obj.service.name_ar)

    @staticmethod
    def resolve_service_name_en(obj: Any) -> str:
        return str(obj.service.name_en)

    @staticmethod
    def resolve_service_kind(obj: Any) -> str:
        return str(obj.service.kind)

    @staticmethod
    def resolve_service_active(obj: Any) -> bool:
        return bool(obj.service.active)

    @staticmethod
    def resolve_unit_price(obj: Any) -> str:
        return str(money(obj.unit_price))


class VersionItemParams(Schema):
    page: int = Field(1, ge=1)
    page_size: int = Field(25, ge=1, le=100)
    q: str | None = Field(None, max_length=200)
    kind: ServiceKindCode | None = None


class PriceChangeIn(Schema):
    service_id: int
    unit_price: MoneyIn | None = Field(..., description="null removes the service")


class PriceChangesIn(Schema):
    items: list[PriceChangeIn] = Field(..., min_length=1, max_length=2000)


class BulkUpdateIn(Schema):
    percent: PercentIn = Field(..., description="e.g. 10 for +10%, -5 for -5%")
    effective_from: date
    step: MoneyIn = Field("0.01", description="Round new prices to a multiple of this")
    mode: RoundModeCode = "half_up"
    kinds: list[ServiceKindCode] | None = Field(None, description="Only these kinds change")
    service_ids: list[int] | None = Field(None, max_length=5000)
    note: str = Field("", max_length=300)


class BulkPreviewRowOut(Schema):
    """Built from ``services.BulkPreviewRow``."""

    service_id: int
    service_code: str
    service_name_ar: str
    service_name_en: str
    service_kind: ServiceKindCode
    old_price: MoneyStr
    new_price: MoneyStr
    changed: bool

    @staticmethod
    def resolve_service_id(obj: Any) -> int:
        return int(obj.service.pk)

    @staticmethod
    def resolve_service_code(obj: Any) -> str:
        return str(obj.service.code)

    @staticmethod
    def resolve_service_name_ar(obj: Any) -> str:
        return str(obj.service.name_ar)

    @staticmethod
    def resolve_service_name_en(obj: Any) -> str:
        return str(obj.service.name_en)

    @staticmethod
    def resolve_service_kind(obj: Any) -> str:
        return str(obj.service.kind)

    @staticmethod
    def resolve_old_price(obj: Any) -> str:
        return str(obj.old_price)

    @staticmethod
    def resolve_new_price(obj: Any) -> str:
        return str(obj.new_price)


class BulkPreviewOut(Schema):
    """Built from ``services.BulkPreview``."""

    base_version: VersionOut
    effective_from: date
    percent: str
    changed_count: int
    rows: list[BulkPreviewRowOut]

    @staticmethod
    def resolve_base_version(obj: Any) -> Any:
        return obj.base

    @staticmethod
    def resolve_percent(obj: Any) -> str:
        return f"{obj.percent:.2f}"


# --- Payers, coverage rules and exclusions --------------------------------------------------


class PayerSummaryOut(Schema):
    """What any catalog reader may see of a payer (no contract or contact details)."""

    id: int
    code: str
    name_ar: str
    name_en: str
    kind: PayerKindCode
    active: bool
    requires_card_number: bool


class PayerListOut(PayerSummaryOut):
    price_list_id: int | None
    price_list_code: str | None
    contract_no: str
    contract_start: date | None
    contract_end: date | None
    claim_period: ClaimPeriodCode

    @staticmethod
    def resolve_price_list_code(obj: Any) -> str | None:
        return obj.price_list.code if obj.price_list_id else None


class CoverageRuleOut(Schema):
    id: int
    service_id: int | None
    service_code: str | None
    service_name_ar: str | None
    service_name_en: str | None
    service_kind: ServiceKindCode | None = Field(..., description="Scope when no service")
    scope: Literal["service", "kind", "default"]
    rule_kind: RuleKindCode
    payer_percent: str | None
    copay_amount: MoneyStr | None
    ceiling_amount: MoneyStr | None
    requires_pre_approval: bool
    note: str
    active: bool

    @staticmethod
    def resolve_service_code(obj: Any) -> str | None:
        return obj.service.code if obj.service_id else None

    @staticmethod
    def resolve_service_name_ar(obj: Any) -> str | None:
        return obj.service.name_ar if obj.service_id else None

    @staticmethod
    def resolve_service_name_en(obj: Any) -> str | None:
        return obj.service.name_en if obj.service_id else None

    @staticmethod
    def resolve_service_kind(obj: Any) -> str | None:
        return obj.service_kind or None

    @staticmethod
    def resolve_scope(obj: Any) -> str:
        if obj.service_id:
            return "service"
        return "kind" if obj.service_kind else "default"

    @staticmethod
    def resolve_payer_percent(obj: Any) -> str | None:
        return _pct(obj.payer_percent)

    @staticmethod
    def resolve_copay_amount(obj: Any) -> str | None:
        return _money(obj.copay_amount)

    @staticmethod
    def resolve_ceiling_amount(obj: Any) -> str | None:
        return _money(obj.ceiling_amount)


class ExclusionOut(Schema):
    id: int
    service_id: int | None
    service_code: str | None
    service_name_ar: str | None
    service_name_en: str | None
    service_kind: ServiceKindCode | None
    note: str
    active: bool

    @staticmethod
    def resolve_service_code(obj: Any) -> str | None:
        return obj.service.code if obj.service_id else None

    @staticmethod
    def resolve_service_name_ar(obj: Any) -> str | None:
        return obj.service.name_ar if obj.service_id else None

    @staticmethod
    def resolve_service_name_en(obj: Any) -> str | None:
        return obj.service.name_en if obj.service_id else None

    @staticmethod
    def resolve_service_kind(obj: Any) -> str | None:
        return obj.service_kind or None


class PayerOut(PayerListOut):
    contact_name: str
    phone: str
    email: str
    address: str
    notes: str
    coverage_rules: list[CoverageRuleOut]
    exclusions: list[ExclusionOut]

    @staticmethod
    def resolve_coverage_rules(obj: Any) -> list[Any]:
        return list(obj.coverage_rules.all())

    @staticmethod
    def resolve_exclusions(obj: Any) -> list[Any]:
        return list(obj.exclusions.all())


class PayerFields(Schema):
    name_ar: str = Field(..., min_length=1, max_length=200)
    name_en: str = Field(..., min_length=1, max_length=200)
    kind: PayerKindCode = "insurance"
    price_list_id: int | None = None
    contract_no: str = Field("", max_length=100)
    contract_start: date | None = None
    contract_end: date | None = None
    claim_period: ClaimPeriodCode = "monthly"
    requires_card_number: bool = True
    contact_name: str = Field("", max_length=150)
    phone: str = Field("", max_length=50)
    email: str = Field("", max_length=254)
    address: str = Field("", max_length=300)
    notes: str = Field("", max_length=2000)
    active: bool = True


class PayerIn(PayerFields):
    code: str = Field(..., pattern=LIST_CODE)


class PayerPatch(PatchSchema):
    NULLABLE: ClassVar[frozenset[str]] = frozenset(
        {"price_list_id", "contract_start", "contract_end"}
    )

    name_ar: str | None = Field(None, min_length=1, max_length=200)
    name_en: str | None = Field(None, min_length=1, max_length=200)
    kind: PayerKindCode | None = None
    price_list_id: int | None = None
    contract_no: str | None = Field(None, max_length=100)
    contract_start: date | None = None
    contract_end: date | None = None
    claim_period: ClaimPeriodCode | None = None
    requires_card_number: bool | None = None
    contact_name: str | None = Field(None, max_length=150)
    phone: str | None = Field(None, max_length=50)
    email: str | None = Field(None, max_length=254)
    address: str | None = Field(None, max_length=300)
    notes: str | None = Field(None, max_length=2000)
    active: bool | None = None


class PayerListParams(Schema):
    page: int = Field(1, ge=1)
    page_size: int = Field(25, ge=1, le=100)
    q: str | None = Field(None, max_length=200)
    active: bool | None = None


class RuleAmounts(Schema):
    rule_kind: RuleKindCode
    payer_percent: PercentIn | None = None
    copay_amount: MoneyIn | None = None
    ceiling_amount: MoneyIn | None = None


class CoverageRuleIn(RuleAmounts):
    service_id: int | None = Field(None, description="Scope: one service")
    service_kind: ServiceKindCode | None = Field(None, description="Scope: a kind of service")
    requires_pre_approval: bool = False
    note: str = Field("", max_length=300)
    active: bool = True


class CoverageRulePatch(PatchSchema):
    NULLABLE: ClassVar[frozenset[str]] = frozenset(
        {"payer_percent", "copay_amount", "ceiling_amount"}
    )

    rule_kind: RuleKindCode | None = None
    payer_percent: PercentIn | None = None
    copay_amount: MoneyIn | None = None
    ceiling_amount: MoneyIn | None = None
    requires_pre_approval: bool | None = None
    note: str | None = Field(None, max_length=300)
    active: bool | None = None


class ExclusionIn(Schema):
    service_id: int | None = None
    service_kind: ServiceKindCode | None = None
    note: str = Field("", max_length=300)


class ExclusionPatch(PatchSchema):
    note: str | None = Field(None, max_length=300)
    active: bool | None = None


class CoveragePreviewIn(RuleAmounts):
    gross: MoneyIn = Field("10000", description="Example line amount")


class CoveragePreviewOut(Schema):
    gross: MoneyStr
    payer_share: MoneyStr
    patient_share: MoneyStr
