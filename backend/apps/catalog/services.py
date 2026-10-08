"""Catalog services: dated price list versions, effective prices and coverage lookup.

FEATURES 5.1-5.8, invariant 6. Every rule comes from ``domain.pricing`` and
``domain.coverage``; this module loads rows, calls the rule and stores the result.

* A price list version is a complete, dated snapshot of prices. The version that prices a
  line is the one effective on the invoice approval date (``effective_version``).
* New versions start tomorrow or later on a free date (no backdating, and no second version
  for a day that already has one effective: either would change which prices were effective
  on a day whose invoices are already frozen). Only a list with nothing effective yet may
  start today.
* A bulk percentage update creates a NEW dated version from the version effective on that
  date; the old version is never edited.
* Only versions that have not started yet may have their prices edited.
* ``resolve_coverage`` picks the most specific active coverage rule of a payer for a service
  (service, then service kind, then the payer default) and reports exclusions.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pghistory
from django.db import connection, transaction
from django.db.models import Count, Prefetch, Q, QuerySet
from django.utils import timezone

from apps.catalog.models import (
    ClaimPeriod,
    CoverageRule,
    CoverageRuleKind,
    Exclusion,
    Payer,
    PayerKind,
    PriceItem,
    PriceList,
    PriceListKind,
    PriceListVersion,
    Service,
    ServiceCategory,
    ServiceKind,
)
from apps.core.models import Department, User
from domain import coverage as dc
from domain import pricing
from domain.errors import DomainError
from domain.money import CENT, HUNDRED, ZERO

__all__ = [
    "EffectivePrice",
    "ResolvedCoverage",
    "bulk_percentage_update",
    "create_version",
    "default_price_list",
    "derive_version",
    "effective_price",
    "effective_prices",
    "effective_version",
    "lock_versions_for_pricing",
    "price_list_for",
    "resolve_coverage",
    "set_prices",
    "version_prices",
]


@dataclass(frozen=True, slots=True)
class EffectivePrice:
    """The price that freezes on an invoice line (invariant 6)."""

    price_list: PriceList
    version: PriceListVersion
    unit_price: Decimal


@dataclass(frozen=True, slots=True)
class ResolvedCoverage:
    """How a payer shares one service with the patient.

    ``rule`` is the stored rule (None when the payer has no applicable rule: the payer then
    covers nothing). ``domain_rule`` is the same rule for ``domain.coverage.split_line``.
    """

    payer: Payer
    rule: CoverageRule | None
    domain_rule: dc.CoverageRule | None
    excluded: bool

    @property
    def requires_preapproval(self) -> bool:
        return bool(self.domain_rule and self.domain_rule.requires_preapproval)


# --- price lists ---------------------------------------------------------------------------


def default_price_list() -> PriceList:
    """The default cash list (seeded by ``catalog.0002``)."""
    found = PriceList.objects.filter(is_default=True).first()
    if found is None:
        raise DomainError("NO_DEFAULT_PRICE_LIST", "No default cash price list is configured")
    return found


def price_list_for(payer: Payer | None) -> PriceList:
    """The payer's contract list, or the default cash list for cash lines and list-less payers."""
    if payer is not None and payer.price_list is not None:
        return payer.price_list
    return default_price_list()


def _versions(price_list: PriceList) -> list[pricing.PriceVersion]:
    return [
        pricing.PriceVersion(v.pk, v.effective_from)
        for v in PriceListVersion.objects.filter(price_list=price_list).only("id", "effective_from")
    ]


def effective_version(price_list: PriceList, on: date) -> PriceListVersion:
    """The version of ``price_list`` effective on ``on`` (``NO_EFFECTIVE_PRICE_LIST``)."""
    chosen = pricing.effective_version(_versions(price_list), on)
    return PriceListVersion.objects.get(pk=chosen.version_id)


def lock_versions_for_pricing(version_ids: Collection[int]) -> None:
    """``FOR SHARE`` the versions an invoice approval prices from (invariant 6).

    Edits of a version's prices lock it ``FOR UPDATE`` (its guard trigger), so an edit and an
    approval never interleave: the approval either prices the committed edit or holds the
    edit back until its frozen lines make the version read-only.
    """
    ids = sorted(set(version_ids))
    if ids:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM catalog_pricelistversion WHERE id = ANY(%s) ORDER BY id FOR SHARE",
                [ids],
            )


def version_prices(version: PriceListVersion) -> dict[int, Decimal]:
    """``{service_id: unit_price}`` of one version."""
    return dict(PriceItem.objects.filter(version=version).values_list("service_id", "unit_price"))


def effective_price(
    service: Service, *, on: date, payer: Payer | None = None, price_list: PriceList | None = None
) -> EffectivePrice:
    """Unit price of ``service`` on ``on`` from the payer's list (or ``price_list``).

    Raises:
        DomainError: ``NO_EFFECTIVE_PRICE_LIST``, ``PRICE_NOT_FOUND``.
    """
    return effective_prices([service], on=on, payer=payer, price_list=price_list)[service.pk]


def effective_prices(
    services: Iterable[Service],
    *,
    on: date,
    payer: Payer | None = None,
    price_list: PriceList | None = None,
) -> dict[int, EffectivePrice]:
    """Batch form of :func:`effective_price`, keyed by service id."""
    plist = price_list or price_list_for(payer)
    version = effective_version(plist, on)
    wanted = {s.pk for s in services}
    prices: dict[pricing.ItemKey, Decimal] = {}
    for service_id, price in PriceItem.objects.filter(
        version=version, service_id__in=wanted
    ).values_list("service_id", "unit_price"):
        prices[service_id] = price
    domain_version = pricing.PriceVersion(version.pk, version.effective_from, prices)
    out: dict[int, EffectivePrice] = {}
    for service_id in sorted(wanted):
        price = pricing.unit_price([domain_version], service_id, on)
        out[service_id] = EffectivePrice(plist, version, price)
    return out


def _check_services(service_ids: Collection[int]) -> None:
    known = set(Service.objects.filter(pk__in=service_ids).values_list("pk", flat=True))
    unknown = sorted(set(service_ids) - known)
    if unknown:
        raise DomainError("SERVICE_UNKNOWN", "Unknown services in the price list", services=unknown)


def create_version(
    price_list: PriceList,
    *,
    effective_from: date,
    prices: Mapping[int, Decimal],
    actor: User,
    note: str = "",
    based_on: PriceListVersion | None = None,
    percent_change: Decimal | None = None,
    today: date | None = None,
) -> PriceListVersion:
    """Create a complete dated version of ``price_list`` (FEATURES 5.2).

    Raises:
        DomainError: ``PRICE_VERSION_BACKDATED``, ``PRICE_VERSION_DATE_TAKEN``,
            ``INVALID_PRICE``, ``SERVICE_UNKNOWN``, ``PRICE_LIST_INACTIVE``.
    """
    # Validates every price (non-negative, at most 2 decimals) before touching the database.
    # (a comprehension, not dict(): mapping key types are invariant for the type checker)
    snapshot = pricing.PriceVersion(0, effective_from, {sid: p for sid, p in prices.items()})  # noqa: C416
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="price list version"):
        # One writer per list at a time, so two versions can never take the same date.
        plist = PriceList.objects.select_for_update(no_key=True).get(pk=price_list.pk)
        if not plist.active:
            raise DomainError("PRICE_LIST_INACTIVE", "The price list is inactive")
        pricing.validate_new_version(
            _versions(plist), effective_from, today or timezone.localdate()
        )
        _check_services([int(sid) for sid in snapshot.prices])
        version = PriceListVersion.objects.create(
            price_list=plist,
            effective_from=effective_from,
            based_on=based_on,
            percent_change=percent_change,
            note=note[:300],
            created_by=actor,
        )
        PriceItem.objects.bulk_create(
            [
                PriceItem(version=version, service_id=int(service_id), unit_price=price)
                for service_id, price in sorted(snapshot.prices.items(), key=lambda kv: kv[0])
            ]
        )
    return version


def derive_version(
    price_list: PriceList,
    *,
    effective_from: date,
    actor: User,
    changes: Mapping[int, Decimal | None],
    note: str = "",
    today: date | None = None,
) -> PriceListVersion:
    """A new version copying the one effective on ``effective_from`` with ``changes`` applied.

    ``changes`` maps service id to its new price, or None to drop the service from the list.
    A list without any version yet starts from an empty snapshot. The base is read under the
    price list lock, so two derivations on one list never build on a stale base.
    """
    with transaction.atomic():
        PriceList.objects.select_for_update(no_key=True).get(pk=price_list.pk)
        try:
            base: PriceListVersion | None = effective_version(price_list, effective_from)
        except DomainError as exc:
            if exc.code != "NO_EFFECTIVE_PRICE_LIST":
                raise
            base = None
        prices = version_prices(base) if base is not None else {}
        for service_id, price in changes.items():
            if price is None:
                prices.pop(service_id, None)
            else:
                prices[service_id] = price
        return create_version(
            price_list,
            effective_from=effective_from,
            prices=prices,
            actor=actor,
            note=note,
            based_on=base,
            today=today,
        )


def bulk_percentage_update(
    price_list: PriceList,
    *,
    percent: Decimal | int,
    effective_from: date,
    actor: User,
    step: Decimal = CENT,
    mode: pricing.RoundMode = pricing.RoundMode.HALF_UP,
    service_ids: Collection[int] | None = None,
    kinds: Collection[str] | None = None,
    note: str = "",
    today: date | None = None,
) -> PriceListVersion:
    """New dated version: prices of the version effective on ``effective_from`` scaled by
    ``percent`` and rounded to ``step`` (FEATURES 5.2). The base version is untouched.

    ``service_ids`` and/or ``kinds`` restrict the change; other prices are copied as they are.

    Raises:
        DomainError: ``NO_EFFECTIVE_PRICE_LIST`` (nothing to base it on), ``INVALID_PERCENT``,
            ``INVALID_ROUNDING_STEP``, ``PRICE_NOT_FOUND`` (a chosen service is not on the list),
            and the errors of :func:`create_version`.
    """
    if isinstance(percent, bool) or not isinstance(percent, Decimal | int):
        raise DomainError("INVALID_PERCENT", "Percent must be a number", percent=str(percent))
    with transaction.atomic():
        # The base is read under the price list lock (concurrent updates never build on a
        # base that an earlier one is about to supersede).
        PriceList.objects.select_for_update(no_key=True).get(pk=price_list.pk)
        base = effective_version(price_list, effective_from)
        base_prices = version_prices(base)
        only: set[int] | None = None
        if service_ids is not None:
            only = set(service_ids)
        if kinds is not None:
            by_kind = set(
                Service.objects.filter(pk__in=base_prices.keys(), kind__in=list(kinds)).values_list(
                    "pk", flat=True
                )
            )
            only = by_kind if only is None else only & by_kind
        rule = pricing.RoundingRule(step, mode)
        new_prices = pricing.bulk_percentage_update(base_prices, percent, rule, only=only)
        return create_version(
            price_list,
            effective_from=effective_from,
            prices=new_prices,
            actor=actor,
            note=note,
            based_on=base,
            percent_change=Decimal(percent).quantize(CENT),
            today=today,
        )


def set_prices(
    version: PriceListVersion,
    prices: Mapping[int, Decimal | None],
    *,
    actor: User,
    today: date | None = None,
) -> PriceListVersion:
    """Edit prices of a version that has not started yet (None removes a service).

    Raises:
        DomainError: ``PRICE_VERSION_LOCKED`` once the version is effective (today or
            earlier): its prices may already be frozen on invoices. Create a new version.
    """
    on = today or timezone.localdate()
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="price edit"):
        locked = PriceListVersion.objects.select_for_update().get(pk=version.pk)
        if locked.effective_from <= on:
            raise DomainError(
                "PRICE_VERSION_LOCKED",
                "A version that is already effective cannot change; create a new version",
                effective_from=locked.effective_from.isoformat(),
            )
        to_set = {sid: p for sid, p in prices.items() if p is not None}
        # Validates every price (non-negative, at most 2 decimals).
        pricing.PriceVersion(locked.pk, locked.effective_from, {k: v for k, v in to_set.items()})  # noqa: C416
        _check_services(to_set.keys())
        removed = [sid for sid, p in prices.items() if p is None]
        if removed:
            PriceItem.objects.filter(version=locked, service_id__in=removed).delete()
        for service_id, price in sorted(to_set.items()):
            PriceItem.objects.update_or_create(
                version=locked, service_id=service_id, defaults={"unit_price": price}
            )
    return locked


# --- coverage ------------------------------------------------------------------------------


def _domain_rule(rule: CoverageRule, patient_percent_override: Decimal | None) -> dc.CoverageRule:
    pre = rule.requires_pre_approval
    if rule.rule_kind == CoverageRuleKind.PERCENTAGE:
        percent = rule.payer_percent if rule.payer_percent is not None else HUNDRED
        if patient_percent_override is not None:
            percent = HUNDRED - patient_percent_override
        return dc.CoverageRule.percentage(Decimal(percent), requires_preapproval=pre)
    if rule.rule_kind == CoverageRuleKind.COPAY:
        return dc.CoverageRule.fixed_copay(
            Decimal(rule.copay_amount or 0), requires_preapproval=pre
        )
    return dc.CoverageRule.capped(
        Decimal(rule.ceiling_amount or 0),
        payer_percent=Decimal(rule.payer_percent if rule.payer_percent is not None else HUNDRED),
        requires_preapproval=pre,
    )


def resolve_coverage(
    payer: Payer, service: Service, *, patient_percent_override: Decimal | None = None
) -> ResolvedCoverage:
    """The payer's applicable rule for ``service`` and whether the service is excluded.

    Most specific active rule wins: the service's own rule, then the rule for its kind, then
    the payer's default rule. ``patient_percent_override`` (from the patient's coverage on
    file) replaces the patient part of a percentage rule.
    """
    excluded = Exclusion.objects.filter(
        Q(service=service) | Q(service__isnull=True, service_kind=service.kind),
        payer=payer,
        active=True,
    ).exists()
    rules = list(
        CoverageRule.objects.filter(
            Q(service=service)
            | Q(service__isnull=True, service_kind=service.kind)
            | Q(service__isnull=True, service_kind=""),
            payer=payer,
            active=True,
        )
    )

    def rank(r: CoverageRule) -> int:
        if r.service_id is not None:
            return 0
        return 1 if r.service_kind else 2

    rule = min(rules, key=rank) if rules else None
    domain_rule = _domain_rule(rule, patient_percent_override) if rule is not None else None
    return ResolvedCoverage(payer=payer, rule=rule, domain_rule=domain_rule, excluded=excluded)


# =========================================================================================
# Administration of the catalog (FEATURES 5.1, 5.2, 11.1). Writes are audited (pghistory
# context with the acting user). Prices and splits come from ``domain.pricing`` and
# ``domain.coverage``; the screens never compute money themselves.
# =========================================================================================

_SERVICE_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.-]{0,39}\Z")
_LIST_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_-]{0,29}\Z")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+\Z")


def _code(value: str, pattern: re.Pattern[str]) -> str:
    text = (value or "").strip()
    if not pattern.match(text):
        raise DomainError(
            "INVALID_CODE",
            "Codes use upper-case letters, digits, '-' and '_' and start with a letter",
            value=text,
        )
    return text


def _clean(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


def _only(fields: Mapping[str, object], allowed: set[str], what: str) -> None:
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Not editable {what} fields: {sorted(unknown)}")


def _department(department_id: int | None) -> Department | None:
    if department_id is None:
        return None
    dept = Department.objects.get(pk=department_id)
    if not dept.active:
        raise DomainError("DEPARTMENT_INACTIVE", "The department is inactive", department=dept.code)
    return dept


def _category(category_id: int | None) -> ServiceCategory | None:
    if category_id is None:
        return None
    category = ServiceCategory.objects.get(pk=category_id)
    if not category.active:
        raise DomainError("CATEGORY_INACTIVE", "The category is inactive", category=category.code)
    return category


# --- Services and categories (FEATURES 5.1) -----------------------------------------------


def list_services(
    *,
    q: str | None = None,
    kind: str | None = None,
    department_id: int | None = None,
    category_id: int | None = None,
    active: bool | None = None,
) -> QuerySet[Service]:
    qs = Service.objects.select_related("department", "category")
    text = (q or "").strip()
    if text:
        qs = qs.filter(
            Q(code__icontains=text) | Q(name_ar__icontains=text) | Q(name_en__icontains=text)
        )
    if kind:
        qs = qs.filter(kind=kind)
    if department_id is not None:
        qs = qs.filter(department_id=department_id)
    if category_id is not None:
        qs = qs.filter(category_id=category_id)
    if active is not None:
        qs = qs.filter(active=active)
    return qs.order_by("kind", "sort_order", "code")


def get_service(service_id: int) -> Service:
    return list_services().get(pk=service_id)


def _check_names(name_ar: str, name_en: str) -> None:
    if not name_ar.strip() and not name_en.strip():
        raise DomainError("SERVICE_NAME_REQUIRED", "A service needs an Arabic or English name")


def create_service(
    actor: User,
    *,
    code: str,
    name_ar: str,
    name_en: str,
    kind: str,
    department_id: int | None = None,
    category_id: int | None = None,
    description: str = "",
    active: bool = True,
    sort_order: int = 0,
) -> Service:
    """Add a catalog service (FEATURES 5.1). Its kind never changes afterwards.

    Raises:
        DomainError: ``INVALID_CODE``, ``SERVICE_CODE_TAKEN``, ``SERVICE_NAME_REQUIRED``,
            ``SERVICE_KIND_UNKNOWN``, ``DEPARTMENT_INACTIVE``, ``CATEGORY_INACTIVE``.
    """
    value = _code(code, _SERVICE_CODE_RE)
    _check_names(name_ar, name_en)
    if kind not in ServiceKind.values:
        raise DomainError("SERVICE_KIND_UNKNOWN", "Unknown service kind", kind=kind)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="create service"):
        if Service.objects.filter(code__iexact=value).exists():
            raise DomainError("SERVICE_CODE_TAKEN", "This service code exists", value=value)
        service = Service.objects.create(
            code=value,
            name_ar=name_ar.strip(),
            name_en=name_en.strip(),
            kind=kind,
            department=_department(department_id),
            category=_category(category_id),
            description=description.strip(),
            active=active,
            sort_order=sort_order,
        )
    return get_service(service.pk)


def update_service(actor: User, service_id: int, **fields: object) -> Service:
    """Edit names, department, category, description, order or the active flag."""
    _only(
        fields,
        {
            "name_ar",
            "name_en",
            "department_id",
            "category_id",
            "description",
            "active",
            "sort_order",
        },
        "service",
    )
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="edit service"):
        service = Service.objects.select_for_update().get(pk=service_id)
        for attr, value in fields.items():
            if attr == "department_id":
                service.department = _department(value)  # type: ignore[arg-type]
            elif attr == "category_id":
                service.category = _category(value)  # type: ignore[arg-type]
            else:
                setattr(service, attr, _clean(value))
        _check_names(service.name_ar, service.name_en)
        service.save()
    return get_service(service_id)


def list_categories(*, active: bool | None = None) -> QuerySet[ServiceCategory]:
    qs = ServiceCategory.objects.all()
    if active is not None:
        qs = qs.filter(active=active)
    return qs.order_by("sort_order", "code")


def create_category(
    actor: User, *, code: str, name_ar: str, name_en: str, sort_order: int = 0
) -> ServiceCategory:
    value = _code(code, _LIST_CODE_RE)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="create category"):
        if ServiceCategory.objects.filter(code__iexact=value).exists():
            raise DomainError("CATEGORY_CODE_TAKEN", "This category code exists", value=value)
        return ServiceCategory.objects.create(
            code=value, name_ar=name_ar.strip(), name_en=name_en.strip(), sort_order=sort_order
        )


def update_category(actor: User, category_id: int, **fields: object) -> ServiceCategory:
    _only(fields, {"name_ar", "name_en", "sort_order", "active"}, "category")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="edit category"):
        category = ServiceCategory.objects.select_for_update().get(pk=category_id)
        for attr, value in fields.items():
            setattr(category, attr, _clean(value))
        category.save()
    return category


# --- Price lists and versions (FEATURES 5.2) ----------------------------------------------


class VersionStatus:
    PAST = "past"
    CURRENT = "current"
    SCHEDULED = "scheduled"


@dataclass(frozen=True, slots=True)
class VersionRow:
    """One version on the price list timeline."""

    version: PriceListVersion
    status: str
    item_count: int

    @property
    def editable(self) -> bool:
        """Prices change only before the version starts (ADR 0006 (o))."""
        return self.status == VersionStatus.SCHEDULED


@dataclass(frozen=True, slots=True)
class PriceListRow:
    price_list: PriceList
    versions: tuple[VersionRow, ...]
    payer_codes: tuple[str, ...]

    @property
    def current(self) -> VersionRow | None:
        return next((v for v in self.versions if v.status == VersionStatus.CURRENT), None)

    @property
    def next_scheduled(self) -> VersionRow | None:
        scheduled = [v for v in self.versions if v.status == VersionStatus.SCHEDULED]
        return min(scheduled, key=lambda v: v.version.effective_from) if scheduled else None


def _timeline(versions: Iterable[PriceListVersion], today: date) -> tuple[VersionRow, ...]:
    ordered = sorted(versions, key=lambda v: (v.effective_from, v.pk), reverse=True)
    started = [v for v in ordered if v.effective_from <= today]
    current_pk = started[0].pk if started else None
    rows = []
    for v in ordered:
        if v.effective_from > today:
            status = VersionStatus.SCHEDULED
        elif v.pk == current_pk:
            status = VersionStatus.CURRENT
        else:
            status = VersionStatus.PAST
        rows.append(VersionRow(v, status, getattr(v, "item_count", 0)))
    return tuple(rows)


def _versions_qs() -> QuerySet[PriceListVersion]:
    return PriceListVersion.objects.select_related("based_on", "created_by").annotate(
        item_count=Count("items")
    )


def list_price_lists(
    *, active: bool | None = None, today: date | None = None
) -> list[PriceListRow]:
    """Every price list with its version timeline (current and next scheduled version)."""
    on = today or timezone.localdate()
    qs = PriceList.objects.prefetch_related(
        Prefetch("versions", queryset=_versions_qs()),
        Prefetch("payers", queryset=Payer.objects.order_by("code")),
    ).order_by("-is_default", "code")
    if active is not None:
        qs = qs.filter(active=active)
    return [
        PriceListRow(
            price_list=plist,
            versions=_timeline(plist.versions.all(), on),
            payer_codes=tuple(p.code for p in plist.payers.all()),
        )
        for plist in qs
    ]


def get_price_list(price_list_id: int, *, today: date | None = None) -> PriceListRow:
    on = today or timezone.localdate()
    plist = PriceList.objects.get(pk=price_list_id)
    return PriceListRow(
        price_list=plist,
        versions=_timeline(_versions_qs().filter(price_list=plist), on),
        payer_codes=tuple(plist.payers.order_by("code").values_list("code", flat=True)),
    )


def create_price_list(
    actor: User, *, code: str, name_ar: str, name_en: str, kind: str = PriceListKind.PAYER
) -> PriceListRow:
    """Raises ``INVALID_CODE``, ``PRICE_LIST_CODE_TAKEN``, ``PRICE_LIST_KIND_UNKNOWN``."""
    value = _code(code, _LIST_CODE_RE)
    if kind not in PriceListKind.values:
        raise DomainError("PRICE_LIST_KIND_UNKNOWN", "Unknown price list kind", kind=kind)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="create price list"):
        if PriceList.objects.filter(code__iexact=value).exists():
            raise DomainError("PRICE_LIST_CODE_TAKEN", "This price list code exists", value=value)
        plist = PriceList.objects.create(
            code=value, name_ar=name_ar.strip(), name_en=name_en.strip(), kind=kind
        )
    return get_price_list(plist.pk)


def update_price_list(actor: User, price_list_id: int, **fields: object) -> PriceListRow:
    """Rename or (de)activate a list.

    Raises:
        DomainError: ``PRICE_LIST_DEFAULT_REQUIRED`` (the default cash list stays active),
            ``PRICE_LIST_IN_USE`` (an active payer prices from it).
    """
    _only(fields, {"name_ar", "name_en", "active"}, "price list")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="edit price list"):
        plist = PriceList.objects.select_for_update().get(pk=price_list_id)
        for attr, value in fields.items():
            setattr(plist, attr, _clean(value))
        if not plist.active:
            if plist.is_default:
                raise DomainError(
                    "PRICE_LIST_DEFAULT_REQUIRED", "The default cash price list stays active"
                )
            users = list(
                plist.payers.filter(active=True).order_by("code").values_list("code", flat=True)
            )
            if users:
                raise DomainError(
                    "PRICE_LIST_IN_USE", "Active payers price from this list", payers=users
                )
        plist.save()
    return get_price_list(price_list_id)


def add_version(
    actor: User,
    price_list_id: int,
    *,
    effective_from: date,
    copy_from_id: int | None = None,
    note: str = "",
    today: date | None = None,
) -> PriceListVersion:
    """A new dated version of the list (FEATURES 5.2), editable until it starts.

    It starts as a copy of ``copy_from_id`` (a version of the same list) or, by default, of
    the version effective on ``effective_from`` (empty when the list has none yet).

    Raises:
        DomainError: ``PRICE_VERSION_BACKDATED``, ``PRICE_VERSION_DATE_TAKEN``,
            ``PRICE_LIST_INACTIVE``.
    """
    plist = PriceList.objects.get(pk=price_list_id)
    if copy_from_id is None:
        return derive_version(
            plist, effective_from=effective_from, actor=actor, changes={}, note=note, today=today
        )
    source = PriceListVersion.objects.get(pk=copy_from_id, price_list=plist)
    return create_version(
        plist,
        effective_from=effective_from,
        prices=version_prices(source),
        actor=actor,
        note=note,
        based_on=source,
        today=today,
    )


def version_items(
    version_id: int, *, q: str | None = None, kind: str | None = None
) -> QuerySet[PriceItem]:
    qs = PriceItem.objects.filter(version_id=version_id).select_related("service")
    text = (q or "").strip()
    if text:
        qs = qs.filter(
            Q(service__code__icontains=text)
            | Q(service__name_ar__icontains=text)
            | Q(service__name_en__icontains=text)
        )
    if kind:
        qs = qs.filter(service__kind=kind)
    return qs.order_by("service__kind", "service__sort_order", "service__code")


def get_version(version_id: int, *, today: date | None = None) -> VersionRow:
    version = PriceListVersion.objects.get(pk=version_id)
    timeline = _timeline(
        _versions_qs().filter(price_list_id=version.price_list_id), today or timezone.localdate()
    )
    return next(r for r in timeline if r.version.pk == version_id)


def edit_version_prices(
    actor: User,
    version_id: int,
    prices: Mapping[int, Decimal | None],
    *,
    today: date | None = None,
) -> VersionRow:
    """Set (or with None remove) prices of a version that has not started yet.

    Raises:
        DomainError: ``PRICE_VERSION_LOCKED``, ``INVALID_PRICE``, ``SERVICE_UNKNOWN``.
    """
    version = PriceListVersion.objects.get(pk=version_id)
    set_prices(version, prices, actor=actor, today=today)
    return get_version(version_id, today=today)


@dataclass(frozen=True, slots=True)
class BulkPreviewRow:
    service: Service
    old_price: Decimal
    new_price: Decimal

    @property
    def changed(self) -> bool:
        return self.old_price != self.new_price


@dataclass(frozen=True, slots=True)
class BulkPreview:
    base: VersionRow
    effective_from: date
    percent: Decimal
    rows: tuple[BulkPreviewRow, ...]

    @property
    def changed_count(self) -> int:
        return sum(1 for r in self.rows if r.changed)


def preview_bulk_update(
    price_list_id: int,
    *,
    percent: Decimal,
    effective_from: date,
    step: Decimal = CENT,
    mode: pricing.RoundMode = pricing.RoundMode.HALF_UP,
    service_ids: Collection[int] | None = None,
    kinds: Collection[str] | None = None,
    today: date | None = None,
) -> BulkPreview:
    """Before and after prices of a bulk percentage update, without saving anything.

    Uses the same base version, rounding and date rules as :func:`bulk_percentage_update`,
    so the preview shows exactly the version that applying it would create.

    Raises:
        DomainError: ``PRICE_VERSION_BACKDATED``, ``PRICE_VERSION_DATE_TAKEN``,
            ``NO_EFFECTIVE_PRICE_LIST``, ``INVALID_PERCENT``, ``INVALID_ROUNDING_STEP``,
            ``PRICE_NOT_FOUND``.
    """
    on = today or timezone.localdate()
    plist = PriceList.objects.get(pk=price_list_id)
    pricing.validate_new_version(_versions(plist), effective_from, on)
    base = effective_version(plist, effective_from)
    base_prices = version_prices(base)
    only = _bulk_scope(base_prices, service_ids, kinds)
    new_prices = pricing.bulk_percentage_update(
        base_prices, percent, pricing.RoundingRule(step, mode), only=only
    )
    services = Service.objects.in_bulk(list(base_prices))
    rows = sorted(
        (
            BulkPreviewRow(services[sid], base_prices[sid], new_prices[sid])
            for sid in base_prices
            if only is None or sid in only
        ),
        key=lambda r: (r.service.kind, r.service.sort_order, r.service.code),
    )
    return BulkPreview(
        base=get_version(base.pk, today=on),
        effective_from=effective_from,
        percent=Decimal(percent).quantize(CENT),
        rows=tuple(rows),
    )


def _bulk_scope(
    base_prices: Mapping[int, Decimal],
    service_ids: Collection[int] | None,
    kinds: Collection[str] | None,
) -> set[int] | None:
    only: set[int] | None = set(service_ids) if service_ids is not None else None
    if kinds is not None:
        by_kind = set(
            Service.objects.filter(pk__in=list(base_prices), kind__in=list(kinds)).values_list(
                "pk", flat=True
            )
        )
        only = by_kind if only is None else only & by_kind
    return only


def apply_bulk_update(
    actor: User,
    price_list_id: int,
    *,
    percent: Decimal,
    effective_from: date,
    step: Decimal = CENT,
    mode: pricing.RoundMode = pricing.RoundMode.HALF_UP,
    service_ids: Collection[int] | None = None,
    kinds: Collection[str] | None = None,
    note: str = "",
    today: date | None = None,
) -> VersionRow:
    """Create the new dated version a preview showed (:func:`bulk_percentage_update`)."""
    version = bulk_percentage_update(
        PriceList.objects.get(pk=price_list_id),
        percent=percent,
        effective_from=effective_from,
        actor=actor,
        step=step,
        mode=mode,
        service_ids=service_ids,
        kinds=kinds,
        note=note,
        today=today,
    )
    return get_version(version.pk, today=today)


# --- Payers, coverage rules and exclusions (FEATURES 5.5-5.8, 11.1) ------------------------


def list_payers(*, q: str | None = None, active: bool | None = None) -> QuerySet[Payer]:
    qs = Payer.objects.select_related("price_list")
    text = (q or "").strip()
    if text:
        qs = qs.filter(
            Q(code__icontains=text) | Q(name_ar__icontains=text) | Q(name_en__icontains=text)
        )
    if active is not None:
        qs = qs.filter(active=active)
    return qs.order_by("code")


def get_payer(payer_id: int) -> Payer:
    return (
        Payer.objects.select_related("price_list")
        .prefetch_related(
            Prefetch(
                "coverage_rules",
                queryset=CoverageRule.objects.select_related("service").order_by(
                    "-active", "service_id", "service_kind", "pk"
                ),
            ),
            Prefetch(
                "exclusions",
                queryset=Exclusion.objects.select_related("service").order_by(
                    "-active", "service_id", "service_kind", "pk"
                ),
            ),
        )
        .get(pk=payer_id)
    )


_PAYER_FIELDS = {
    "name_ar",
    "name_en",
    "kind",
    "price_list_id",
    "contract_no",
    "contract_start",
    "contract_end",
    "claim_period",
    "requires_card_number",
    "contact_name",
    "phone",
    "email",
    "address",
    "notes",
    "active",
}


def _apply_payer_fields(payer: Payer, fields: Mapping[str, object]) -> None:
    for attr, value in fields.items():
        if attr == "price_list_id":
            plist = PriceList.objects.get(pk=int(str(value))) if value is not None else None
            if plist is not None and not plist.active:
                raise DomainError(
                    "PRICE_LIST_INACTIVE", "The price list is inactive", price_list=plist.code
                )
            payer.price_list = plist
        else:
            setattr(payer, attr, _clean(value))
    if payer.kind not in PayerKind.values:
        raise DomainError("PAYER_KIND_UNKNOWN", "Unknown payer kind", kind=payer.kind)
    if payer.claim_period not in ClaimPeriod.values:
        raise DomainError(
            "CLAIM_PERIOD_UNKNOWN", "Unknown claim period", claim_period=payer.claim_period
        )
    if payer.email and not _EMAIL_RE.match(payer.email):
        raise DomainError("INVALID_EMAIL", "The email address is not valid")
    if (
        payer.contract_start is not None
        and payer.contract_end is not None
        and payer.contract_end < payer.contract_start
    ):
        raise DomainError("PAYER_CONTRACT_DATES", "The contract cannot end before it starts")


def create_payer(actor: User, *, code: str, **fields: object) -> Payer:
    """Add a payer with its contract information (FEATURES 11.1).

    Raises:
        DomainError: ``INVALID_CODE``, ``PAYER_CODE_TAKEN``, ``PAYER_CONTRACT_DATES``,
            ``PRICE_LIST_INACTIVE``, ``INVALID_EMAIL``.
    """
    value = _code(code, _LIST_CODE_RE)
    _only(fields, _PAYER_FIELDS, "payer")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="create payer"):
        if Payer.objects.filter(code__iexact=value).exists():
            raise DomainError("PAYER_CODE_TAKEN", "This payer code exists", value=value)
        payer = Payer(code=value)
        _apply_payer_fields(payer, fields)
        payer.save()
    return get_payer(payer.pk)


def update_payer(actor: User, payer_id: int, **fields: object) -> Payer:
    _only(fields, _PAYER_FIELDS, "payer")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="edit payer"):
        payer = Payer.objects.select_for_update().get(pk=payer_id)
        _apply_payer_fields(payer, fields)
        payer.save()
    return get_payer(payer_id)


def coverage_rule_from_fields(
    rule_kind: str,
    *,
    payer_percent: Decimal | None,
    copay_amount: Decimal | None,
    ceiling_amount: Decimal | None,
    requires_pre_approval: bool = False,
) -> tuple[dc.CoverageRule, dict[str, Decimal | None]]:
    """Check a rule's amounts and return the domain rule and the columns to store.

    Only the columns the kind uses are kept (a percentage rule stores no copay).

    Raises:
        DomainError: ``COVERAGE_RULE_INCOMPLETE`` (``details.field``),
            ``INVALID_COVERAGE_RULE`` (out of range), ``COVERAGE_RULE_KIND_UNKNOWN``.
    """

    def need(name: str, value: Decimal | None) -> Decimal:
        if value is None:
            raise DomainError(
                "COVERAGE_RULE_INCOMPLETE", "The rule is missing an amount", field=name
            )
        return value

    if rule_kind == CoverageRuleKind.PERCENTAGE:
        percent = need("payer_percent", payer_percent)
        rule = dc.CoverageRule.percentage(percent, requires_preapproval=requires_pre_approval)
        stored = {"payer_percent": percent, "copay_amount": None, "ceiling_amount": None}
    elif rule_kind == CoverageRuleKind.COPAY:
        copay = need("copay_amount", copay_amount)
        rule = dc.CoverageRule.fixed_copay(copay, requires_preapproval=requires_pre_approval)
        stored = {"payer_percent": None, "copay_amount": copay, "ceiling_amount": None}
    elif rule_kind == CoverageRuleKind.CEILING:
        ceiling = need("ceiling_amount", ceiling_amount)
        rule = dc.CoverageRule.capped(
            ceiling,
            payer_percent=payer_percent if payer_percent is not None else HUNDRED,
            requires_preapproval=requires_pre_approval,
        )
        stored = {"payer_percent": payer_percent, "copay_amount": None, "ceiling_amount": ceiling}
    else:
        raise DomainError(
            "COVERAGE_RULE_KIND_UNKNOWN", "Unknown coverage rule kind", rule_kind=rule_kind
        )
    return rule, stored


def _rule_scope_filter(rule: CoverageRule) -> Q:
    if rule.service_id is not None:
        return Q(service_id=rule.service_id)
    return Q(service__isnull=True, service_kind=rule.service_kind)


def _check_rule_unique(rule: CoverageRule) -> None:
    if not rule.active:
        return
    clash = (
        CoverageRule.objects.select_for_update()
        .filter(_rule_scope_filter(rule), payer_id=rule.payer_id, active=True)
        .exclude(pk=rule.pk)
        .exists()
    )
    if clash:
        raise DomainError(
            "COVERAGE_RULE_DUPLICATE",
            "The payer already has an active rule for this service, kind or default",
        )


def _scope(service_id: int | None, service_kind: str | None) -> tuple[Service | None, str]:
    kind = service_kind or ""
    if service_id is not None and kind:
        raise DomainError(
            "COVERAGE_SCOPE_INVALID", "Choose a service or a kind of service, not both"
        )
    if kind and kind not in ServiceKind.values:
        raise DomainError("SERVICE_KIND_UNKNOWN", "Unknown service kind", kind=kind)
    service = Service.objects.get(pk=service_id) if service_id is not None else None
    return service, kind


def add_coverage_rule(
    actor: User,
    payer_id: int,
    *,
    rule_kind: str,
    service_id: int | None = None,
    service_kind: str | None = None,
    payer_percent: Decimal | None = None,
    copay_amount: Decimal | None = None,
    ceiling_amount: Decimal | None = None,
    requires_pre_approval: bool = False,
    note: str = "",
    active: bool = True,
) -> CoverageRule:
    """A payer's share rule for one service, a kind of service, or the payer default.

    Raises:
        DomainError: ``COVERAGE_SCOPE_INVALID``, ``COVERAGE_RULE_DUPLICATE`` and the errors of
            :func:`coverage_rule_from_fields`.
    """
    _, stored = coverage_rule_from_fields(
        rule_kind,
        payer_percent=payer_percent,
        copay_amount=copay_amount,
        ceiling_amount=ceiling_amount,
        requires_pre_approval=requires_pre_approval,
    )
    service, kind = _scope(service_id, service_kind)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="coverage rule"):
        payer = Payer.objects.select_for_update().get(pk=payer_id)
        rule = CoverageRule(
            payer=payer,
            service=service,
            service_kind=kind,
            rule_kind=rule_kind,
            requires_pre_approval=requires_pre_approval,
            note=note.strip(),
            active=active,
            **stored,
        )
        _check_rule_unique(rule)
        rule.save()
    return CoverageRule.objects.select_related("service").get(pk=rule.pk)


def update_coverage_rule(actor: User, rule_id: int, **fields: object) -> CoverageRule:
    """Change a rule's kind, amounts, pre-approval flag, note or active flag (not its scope).

    New amounts apply to invoices approved from now on; approved invoices keep their frozen
    shares (invariant 2).
    """
    _only(
        fields,
        {
            "rule_kind",
            "payer_percent",
            "copay_amount",
            "ceiling_amount",
            "requires_pre_approval",
            "note",
            "active",
        },
        "coverage rule",
    )
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="coverage rule"):
        rule = CoverageRule.objects.select_for_update().get(pk=rule_id)
        Payer.objects.select_for_update().get(pk=rule.payer_id)
        merged: dict[str, object] = {
            "rule_kind": rule.rule_kind,
            "payer_percent": rule.payer_percent,
            "copay_amount": rule.copay_amount,
            "ceiling_amount": rule.ceiling_amount,
            "requires_pre_approval": rule.requires_pre_approval,
        }
        merged.update({k: v for k, v in fields.items() if k in merged})
        _, stored = coverage_rule_from_fields(
            str(merged["rule_kind"]),
            payer_percent=merged["payer_percent"],  # type: ignore[arg-type]
            copay_amount=merged["copay_amount"],  # type: ignore[arg-type]
            ceiling_amount=merged["ceiling_amount"],  # type: ignore[arg-type]
            requires_pre_approval=bool(merged["requires_pre_approval"]),
        )
        rule.rule_kind = str(merged["rule_kind"])
        rule.requires_pre_approval = bool(merged["requires_pre_approval"])
        for attr, value in stored.items():
            setattr(rule, attr, value)
        if "note" in fields:
            rule.note = str(fields["note"]).strip()
        if "active" in fields:
            rule.active = bool(fields["active"])
        _check_rule_unique(rule)
        rule.save()
    return CoverageRule.objects.select_related("service").get(pk=rule_id)


def add_exclusion(
    actor: User,
    payer_id: int,
    *,
    service_id: int | None = None,
    service_kind: str | None = None,
    note: str = "",
) -> Exclusion:
    """A service or kind the payer never covers: 100% to the patient (FEATURES 5.7).

    Raises:
        DomainError: ``EXCLUSION_SCOPE_REQUIRED``, ``COVERAGE_SCOPE_INVALID``,
            ``EXCLUSION_DUPLICATE`` (switch the existing one on instead).
    """
    if service_id is None and not service_kind:
        raise DomainError(
            "EXCLUSION_SCOPE_REQUIRED", "Choose the service or kind of service to exclude"
        )
    service, kind = _scope(service_id, service_kind)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="coverage exclusion"):
        payer = Payer.objects.select_for_update().get(pk=payer_id)
        scope = (
            Q(service=service)
            if service is not None
            else Q(service__isnull=True, service_kind=kind)
        )
        if Exclusion.objects.filter(scope, payer=payer).exists():
            raise DomainError("EXCLUSION_DUPLICATE", "This exclusion exists; switch it on instead")
        exclusion = Exclusion.objects.create(
            payer=payer, service=service, service_kind=kind, note=note.strip()
        )
    return Exclusion.objects.select_related("service").get(pk=exclusion.pk)


def update_exclusion(actor: User, exclusion_id: int, **fields: object) -> Exclusion:
    _only(fields, {"note", "active"}, "exclusion")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="coverage exclusion"):
        exclusion = Exclusion.objects.select_for_update().get(pk=exclusion_id)
        for attr, value in fields.items():
            setattr(exclusion, attr, _clean(value))
        exclusion.save()
    return Exclusion.objects.select_related("service").get(pk=exclusion_id)


def preview_coverage(
    *,
    rule_kind: str,
    gross: Decimal,
    payer_percent: Decimal | None = None,
    copay_amount: Decimal | None = None,
    ceiling_amount: Decimal | None = None,
) -> dc.LineSplit:
    """The split of an example line under a rule being edited (no discount, not excluded).

    E.g. 10,000 under a 70% rule gives payer 7,000 / patient 3,000. The screen shows this
    live, so the same ``domain.coverage`` rule that splits invoice lines computes it.
    """
    rule, _ = coverage_rule_from_fields(
        rule_kind,
        payer_percent=payer_percent,
        copay_amount=copay_amount,
        ceiling_amount=ceiling_amount,
    )
    return dc.split_line(gross, ZERO, rule)
