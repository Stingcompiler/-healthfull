"""Catalog services: dated price list versions, effective prices and coverage lookup.

FEATURES 5.1-5.8, invariant 6. Every rule comes from ``domain.pricing`` and
``domain.coverage``; this module loads rows, calls the rule and stores the result.

* A price list version is a complete, dated snapshot of prices. The version that prices a
  line is the one effective on the invoice approval date (``effective_version``).
* New versions start today or later on a free date (no backdating: it would change which
  prices were effective on days whose invoices are already frozen).
* A bulk percentage update creates a NEW dated version from the version effective on that
  date; the old version is never edited.
* Only versions that have not started yet may have their prices edited.
* ``resolve_coverage`` picks the most specific active coverage rule of a payer for a service
  (service, then service kind, then the payer default) and reports exclusions.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pghistory
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.catalog.models import (
    CoverageRule,
    CoverageRuleKind,
    Exclusion,
    Payer,
    PriceItem,
    PriceList,
    PriceListVersion,
    Service,
)
from apps.core.models import User
from domain import coverage as dc
from domain import pricing
from domain.errors import DomainError
from domain.money import CENT, HUNDRED

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
    prices: dict[pricing.ItemKey, Decimal] = {
        service_id: price
        for service_id, price in PriceItem.objects.filter(
            version=version, service_id__in=wanted
        ).values_list("service_id", "unit_price")
    }
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
    snapshot = pricing.PriceVersion(0, effective_from, {sid: p for sid, p in prices.items()})
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="price list version"):
        # One writer per list at a time, so two versions can never take the same date.
        plist = PriceList.objects.select_for_update().get(pk=price_list.pk)
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
    A list without any version yet starts from an empty snapshot.
    """
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
        pricing.PriceVersion(locked.pk, locked.effective_from, {k: v for k, v in to_set.items()})
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
