"""Catalog services: dated price list versions, effective prices, coverage lookup."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.utils import timezone

from apps.catalog import services as cat
from apps.catalog.models import CoverageRule, Exclusion, PriceItem, PriceList, PriceListVersion
from apps.core.tests import builders as b
from domain import coverage as dc
from domain.errors import DomainError
from domain.pricing import RoundMode

pytestmark = pytest.mark.django_db

TODAY = date(2026, 10, 7)


@pytest.fixture
def actor():
    return b.user()


@pytest.fixture
def cash() -> PriceList:
    found = PriceList.objects.filter(is_default=True).first()
    return found or b.price_version().price_list


def _version(plist, on, prices, actor):
    return cat.create_version(plist, effective_from=on, prices=prices, actor=actor, today=on)


def test_effective_version_is_latest_started(cash, actor) -> None:
    s = b.service(kind="lab")
    v1 = _version(cash, TODAY, {s.pk: Decimal("100.00")}, actor)
    v2 = cat.create_version(
        cash,
        effective_from=TODAY + timedelta(days=10),
        prices={s.pk: Decimal("120.00")},
        actor=actor,
        today=TODAY,
    )
    assert cat.effective_version(cash, TODAY) == v1
    assert cat.effective_version(cash, TODAY + timedelta(days=9)) == v1
    assert cat.effective_version(cash, TODAY + timedelta(days=10)) == v2
    assert cat.effective_price(s, on=TODAY + timedelta(days=11)).unit_price == Decimal("120.00")
    with pytest.raises(DomainError) as exc:
        cat.effective_version(cash, TODAY - timedelta(days=1))
    assert exc.value.code == "NO_EFFECTIVE_PRICE_LIST"


def test_price_not_found_and_payer_list(cash, actor) -> None:
    s1, s2 = b.service(), b.service()
    _version(cash, TODAY, {s1.pk: Decimal("50.00")}, actor)
    with pytest.raises(DomainError) as exc:
        cat.effective_price(s2, on=TODAY)
    assert exc.value.code == "PRICE_NOT_FOUND"

    contract = PriceList.objects.create(
        code="INS1", name_ar="عقد", name_en="Contract", kind="payer"
    )
    _version(contract, TODAY, {s1.pk: Decimal("80.00")}, actor)
    insurer = b.payer(price_list=contract)
    plain = b.payer()
    assert cat.effective_price(s1, on=TODAY, payer=insurer).unit_price == Decimal("80.00")
    # A payer without a contract list is priced from the default cash list.
    assert cat.effective_price(s1, on=TODAY, payer=plain).unit_price == Decimal("50.00")
    found = cat.effective_prices([s1], on=TODAY, payer=insurer)[s1.pk]
    assert found.price_list == contract


def test_versions_cannot_be_backdated_or_share_a_date(cash, actor) -> None:
    s = b.service()
    _version(cash, TODAY, {s.pk: Decimal("10.00")}, actor)
    with pytest.raises(DomainError) as exc:
        cat.create_version(
            cash,
            effective_from=TODAY - timedelta(days=1),
            prices={s.pk: Decimal("1.00")},
            actor=actor,
            today=TODAY,
        )
    assert exc.value.code == "PRICE_VERSION_BACKDATED"
    # A second version from today would make two prices "effective today" (invariant 6).
    with pytest.raises(DomainError) as exc:
        _version(cash, TODAY, {s.pk: Decimal("11.00")}, actor)
    assert exc.value.code == "PRICE_VERSION_BACKDATED"
    later = TODAY + timedelta(days=5)
    cat.create_version(
        cash, effective_from=later, prices={s.pk: Decimal("12.00")}, actor=actor, today=TODAY
    )
    with pytest.raises(DomainError) as exc:
        cat.create_version(
            cash, effective_from=later, prices={s.pk: Decimal("13.00")}, actor=actor, today=TODAY
        )
    assert exc.value.code == "PRICE_VERSION_DATE_TAKEN"


def test_invalid_prices_and_unknown_services_are_refused(cash, actor) -> None:
    s = b.service()
    with pytest.raises(DomainError) as exc:
        _version(cash, TODAY, {s.pk: Decimal("-1.00")}, actor)
    assert exc.value.code == "INVALID_PRICE"
    with pytest.raises(DomainError) as exc:
        _version(cash, TODAY, {s.pk: Decimal("1.005")}, actor)
    assert exc.value.code == "INVALID_PRICE"
    with pytest.raises(DomainError) as exc:
        _version(cash, TODAY, {999_999: Decimal("1.00")}, actor)
    assert exc.value.code == "SERVICE_UNKNOWN"
    assert not PriceListVersion.objects.filter(price_list=cash, effective_from=TODAY).exists()


def test_bulk_percentage_update_creates_a_new_dated_version(cash, actor) -> None:
    lab, drug = b.service(kind="lab"), b.service(kind="drug")
    base = _version(cash, TODAY, {lab.pk: Decimal("100.00"), drug.pk: Decimal("33.00")}, actor)
    new = cat.bulk_percentage_update(
        cash,
        percent=15,
        effective_from=TODAY + timedelta(days=1),
        actor=actor,
        step=Decimal("5.00"),
        mode=RoundMode.HALF_UP,
        today=TODAY,
    )
    assert new.based_on == base
    assert new.percent_change == Decimal("15.00")
    assert cat.version_prices(new) == {lab.pk: Decimal("115.00"), drug.pk: Decimal("40.00")}
    # The base version is untouched: invoices priced from it keep their history.
    assert cat.version_prices(base) == {lab.pk: Decimal("100.00"), drug.pk: Decimal("33.00")}
    assert cat.effective_price(lab, on=TODAY).unit_price == Decimal("100.00")
    assert cat.effective_price(lab, on=TODAY + timedelta(days=1)).unit_price == Decimal("115.00")


def test_bulk_update_restricted_by_kind(cash, actor) -> None:
    lab, drug = b.service(kind="lab"), b.service(kind="drug")
    _version(cash, TODAY, {lab.pk: Decimal("100.00"), drug.pk: Decimal("40.00")}, actor)
    new = cat.bulk_percentage_update(
        cash,
        percent=Decimal("-10"),
        effective_from=TODAY + timedelta(days=3),
        actor=actor,
        kinds=["drug"],
        today=TODAY,
    )
    assert cat.version_prices(new) == {lab.pk: Decimal("100.00"), drug.pk: Decimal("36.00")}


def test_bulk_update_rejects_bad_percent_and_unknown_services(cash, actor) -> None:
    s = b.service()
    _version(cash, TODAY, {s.pk: Decimal("100.00")}, actor)
    for bad in (-100, 1001):
        with pytest.raises(DomainError) as exc:
            cat.bulk_percentage_update(
                cash,
                percent=bad,
                effective_from=TODAY + timedelta(days=1),
                actor=actor,
                today=TODAY,
            )
        assert exc.value.code == "INVALID_PERCENT"
    with pytest.raises(DomainError) as exc:
        cat.bulk_percentage_update(
            cash,
            percent=5,
            effective_from=TODAY + timedelta(days=1),
            actor=actor,
            service_ids=[b.service().pk],
            today=TODAY,
        )
    assert exc.value.code == "PRICE_NOT_FOUND"
    float_percent: Any = 5.5
    with pytest.raises(DomainError) as exc:
        cat.bulk_percentage_update(
            cash,
            percent=float_percent,
            effective_from=TODAY + timedelta(days=1),
            actor=actor,
            today=TODAY,
        )
    assert exc.value.code == "INVALID_PERCENT"


def test_derive_version_applies_changes(cash, actor) -> None:
    a, c, d = b.service(), b.service(), b.service()
    _version(cash, TODAY, {a.pk: Decimal("10.00"), c.pk: Decimal("20.00")}, actor)
    new = cat.derive_version(
        cash,
        effective_from=TODAY + timedelta(days=2),
        actor=actor,
        changes={a.pk: Decimal("12.00"), c.pk: None, d.pk: Decimal("5.00")},
        today=TODAY,
    )
    assert cat.version_prices(new) == {a.pk: Decimal("12.00"), d.pk: Decimal("5.00")}


def test_only_future_versions_can_be_edited(cash, actor) -> None:
    s, t = b.service(), b.service()
    current = _version(cash, TODAY, {s.pk: Decimal("10.00")}, actor)
    with pytest.raises(DomainError) as exc:
        cat.set_prices(current, {s.pk: Decimal("11.00")}, actor=actor, today=TODAY)
    assert exc.value.code == "PRICE_VERSION_LOCKED"
    future = cat.create_version(
        cash,
        effective_from=TODAY + timedelta(days=5),
        prices={s.pk: Decimal("10.00")},
        actor=actor,
        today=TODAY,
    )
    cat.set_prices(
        future, {s.pk: Decimal("13.00"), t.pk: Decimal("7.00")}, actor=actor, today=TODAY
    )
    assert cat.version_prices(future) == {s.pk: Decimal("13.00"), t.pk: Decimal("7.00")}
    cat.set_prices(future, {t.pk: None}, actor=actor, today=TODAY)
    assert cat.version_prices(future) == {s.pk: Decimal("13.00")}
    # The day it starts, it is locked.
    with pytest.raises(DomainError) as exc:
        cat.set_prices(
            future, {s.pk: Decimal("1.00")}, actor=actor, today=TODAY + timedelta(days=5)
        )
    assert exc.value.code == "PRICE_VERSION_LOCKED"


def test_price_history_is_recorded_with_actor(cash, actor) -> None:
    s = b.service()
    version = _version(cash, timezone.localdate(), {s.pk: Decimal("10.00")}, actor)
    item = PriceItem.objects.get(version=version)
    events = item.events.all()  # type: ignore[attr-defined]
    assert events.count() == 1
    assert events.first().pgh_context.metadata["user"] == actor.pk


def test_inactive_price_list_refuses_versions(actor) -> None:
    plist = PriceList.objects.create(
        code="OLD", name_ar="قديم", name_en="Old", kind="payer", active=False
    )
    with pytest.raises(DomainError) as exc:
        _version(plist, TODAY, {}, actor)
    assert exc.value.code == "PRICE_LIST_INACTIVE"


# --- coverage --------------------------------------------------------------------------------


def test_resolve_coverage_most_specific_rule_wins() -> None:
    payer = b.payer()
    lab = b.service(kind="lab")
    drug = b.service(kind="drug")
    CoverageRule.objects.create(payer=payer, rule_kind="percentage", payer_percent=Decimal(70))
    CoverageRule.objects.create(
        payer=payer, service_kind="lab", rule_kind="copay", copay_amount=Decimal("50.00")
    )
    CoverageRule.objects.create(
        payer=payer,
        service=lab,
        rule_kind="ceiling",
        ceiling_amount=Decimal("300.00"),
        payer_percent=Decimal(90),
        requires_pre_approval=True,
    )
    lab_cov = cat.resolve_coverage(payer, lab)
    assert lab_cov.domain_rule == dc.CoverageRule.capped(
        Decimal("300.00"), payer_percent=Decimal(90), requires_preapproval=True
    )
    assert lab_cov.requires_preapproval
    other_lab = b.service(kind="lab")
    assert cat.resolve_coverage(payer, other_lab).domain_rule == dc.CoverageRule.fixed_copay(
        Decimal("50.00")
    )
    drug_cov = cat.resolve_coverage(payer, drug)
    assert drug_cov.domain_rule == dc.CoverageRule.percentage(Decimal(70))
    assert not drug_cov.excluded
    # The patient's override replaces the patient part of a percentage rule.
    overridden = cat.resolve_coverage(payer, drug, patient_percent_override=Decimal(10))
    assert overridden.domain_rule == dc.CoverageRule.percentage(Decimal(90))


def test_resolve_coverage_exclusions_and_no_rule() -> None:
    payer = b.payer()
    drug = b.service(kind="drug")
    proc = b.service(kind="procedure")
    assert cat.resolve_coverage(payer, drug).domain_rule is None
    Exclusion.objects.create(payer=payer, service_kind="drug")
    Exclusion.objects.create(payer=payer, service=proc)
    assert cat.resolve_coverage(payer, drug).excluded
    assert cat.resolve_coverage(payer, proc).excluded
    assert not cat.resolve_coverage(payer, b.service(kind="lab")).excluded
    # Inactive rules and exclusions do not apply.
    Exclusion.objects.filter(payer=payer).update(active=False)
    assert not cat.resolve_coverage(payer, drug).excluded


def test_no_default_price_list_is_a_domain_error() -> None:
    PriceList.objects.filter(is_default=True).update(is_default=False)
    with pytest.raises(DomainError) as exc:
        cat.default_price_list()
    assert exc.value.code == "NO_DEFAULT_PRICE_LIST"
