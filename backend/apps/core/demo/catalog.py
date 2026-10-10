"""Write the demo center's configuration (``apps.core.demo.data``) on its opening day.

Runs under the simulated clock (``clock.py``) on the first day of the demo month, so price
lists, payers and opening stock all start on that day. Rows are created through the services
where one exists (services, categories, price lists and versions, payers and their rules,
stock items, units and goods receipts, lab tests, parameters and ranges, beds) and written
directly only for configuration without a service (center profile, users and roles,
departments, rooms, doctor profiles and schedules, stores, suppliers, tills), the way
``seed_e2e`` does. Each part is skipped when it already exists, so a second run creates
nothing twice.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from apps.catalog import services as catalog_services
from apps.catalog.models import Payer, PriceList, PriceListVersion, Service, ServiceCategory
from apps.core import roles
from apps.core.demo import data
from apps.core.models import (
    CenterProfile,
    Department,
    DoctorProfile,
    Language,
    Policy,
    ReasonCode,
    Role,
    Room,
    Theme,
    User,
    UserRole,
)
from apps.core.reason_codes import REASON_CODES, ensure_reason_codes
from apps.lab import services as lab_services
from apps.lab.models import LabTest
from apps.payments.models import Bank, Till
from apps.pharmacy import services as pharmacy_services
from apps.pharmacy.models import DrugClass, GoodsReceipt, Item, Store, Supplier
from apps.visits import services as visit_services
from apps.visits.models import Bed, DoctorSchedule
from domain.money import q

#: Test value for every demo account (docs/runbooks/demo.md). Never a real password.
DEMO_PASSWORD = "Demo-Pass-2026"  # noqa: S105 - demo value, documented in the runbook

__all__ = ["DEMO_PASSWORD", "Catalog", "seed_catalog"]


@dataclass(slots=True)
class Catalog:
    """What the activity needs from the configuration, by code."""

    users: dict[str, User] = field(default_factory=dict)
    doctors: dict[str, DoctorProfile] = field(default_factory=dict)
    departments: dict[str, Department] = field(default_factory=dict)
    services: dict[str, Service] = field(default_factory=dict)
    payers: dict[str, Payer] = field(default_factory=dict)
    stores: dict[str, Store] = field(default_factory=dict)
    suppliers: dict[str, Supplier] = field(default_factory=dict)
    items: dict[str, Item] = field(default_factory=dict)
    beds: dict[str, Bed] = field(default_factory=dict)
    banks: dict[str, Bank] = field(default_factory=dict)
    created: dict[str, int] = field(default_factory=dict)

    def count(self, what: str, n: int = 1) -> None:
        self.created[what] = self.created.get(what, 0) + n


# --- people and places ----------------------------------------------------------------------------


def _center() -> None:
    center = CenterProfile.load()
    changed = [k for k, v in data.CENTER.items() if getattr(center, k) != v]
    for key in changed:
        setattr(center, key, data.CENTER[key])
    if changed:
        center.save()
    Policy.load()


def _user(username: str, name_ar: str, name_en: str, role: str, cat: Catalog) -> User:
    """Create the account when missing; an existing account keeps its password (a demo run
    on an e2e database must not change the e2e accounts' known password)."""
    user = User.objects.filter(username=username).first()
    if user is None:
        user = User(
            username=username,
            full_name_ar=name_ar,
            full_name_en=name_en,
            email=f"{username.replace('.', '-')}@demo.example.test",
            must_change_password=False,
            language=Language.AR,
            theme=Theme.LIGHT,
        )
        user.set_password(DEMO_PASSWORD)
        user.save()
        cat.count("users")
    UserRole.objects.get_or_create(user=user, role=Role.objects.get(code=role))
    return user


def _people(cat: Catalog) -> None:
    for r in roles.ROLES:
        Role.objects.update_or_create(
            code=r.code, defaults={"name_ar": r.name_ar, "name_en": r.name_en}
        )
    for staff in data.STAFF:
        cat.users[staff.username] = _user(
            staff.username, staff.full_name_ar, staff.full_name_en, staff.role, cat
        )
    for doc in data.DOCTORS:
        cat.users[doc.username] = _user(
            doc.username, doc.full_name_ar, doc.full_name_en, roles.DOCTOR, cat
        )


def _places(cat: Catalog) -> dict[str, Room]:
    units = (*data.CLINICAL_DEPARTMENTS, *data.SERVICE_UNITS)
    for order, (code, name_ar, name_en) in enumerate(units, start=1):
        cat.departments[code], _ = Department.objects.update_or_create(
            code=code,
            defaults={"name_ar": name_ar, "name_en": name_en, "active": True, "sort_order": order},
        )
    rooms: dict[str, Room] = {}
    for code, dept, name_ar, name_en in data.ROOMS:
        rooms[code], _ = Room.objects.update_or_create(
            code=code,
            defaults={
                "department": cat.departments[dept],
                "name_ar": name_ar,
                "name_en": name_en,
                "active": True,
            },
        )
    for code, name_ar, name_en in data.TILLS:
        Till.objects.update_or_create(
            code=code, defaults={"name_ar": name_ar, "name_en": name_en, "active": True}
        )
    Bank.objects.filter(active=False).update(active=True)
    cat.banks = {b.code: b for b in Bank.objects.all()}
    ensure_reason_codes()
    for reason in REASON_CODES:
        ReasonCode.objects.filter(category=reason.category, code=reason.code, active=False).update(
            active=True
        )
    return rooms


def _doctors(cat: Catalog, rooms: dict[str, Room]) -> None:
    for doc in data.DOCTORS:
        profile, _ = DoctorProfile.objects.update_or_create(
            user=cat.users[doc.username],
            defaults={
                "department": cat.departments[doc.department],
                "specialty_ar": doc.specialty_ar,
                "specialty_en": doc.specialty_en,
                "consultation_service": cat.services[doc.consultation],
                "active": True,
            },
        )
        for session in doc.sessions:
            for weekday in session.weekdays:
                DoctorSchedule.objects.update_or_create(
                    doctor=profile,
                    weekday=weekday,
                    start_time=session.start,
                    defaults={
                        "end_time": session.end,
                        "slot_minutes": session.slot_minutes,
                        "room": rooms[session.room],
                        "valid_from": None,
                        "valid_to": None,
                        "active": True,
                    },
                )
        cat.doctors[doc.username] = profile


# --- services and prices --------------------------------------------------------------------------


def _all_service_defs() -> list[data.ServiceDef]:
    defs = [*data.CONSULTATIONS, *data.PROCEDURES, *data.BED_SERVICES]
    for t in data.LAB_TESTS:
        defs.append(
            data.ServiceDef(t.service_code, "lab", "LAB", t.category, t.name_ar, t.name_en, t.price)
        )
    for d in data.DRUGS:
        defs.append(
            data.ServiceDef(
                d.service_code,
                "drug",
                "PHA",
                "DRUG",
                f"{d.name_ar} {d.strength}",
                f"{d.generic} {d.strength}",
                d.price,
            )
        )
    for s in data.SUPPLIES:
        defs.append(
            data.ServiceDef(
                s.service_code, "consumable", "PHA", "SUPPLY", s.name_ar, s.name_en, s.price
            )
        )
    return defs


def _services(cat: Catalog, actor: User) -> list[data.ServiceDef]:
    categories: dict[str, ServiceCategory] = {}
    for order, (code, name_ar, name_en) in enumerate(data.CATEGORIES, start=1):
        found = ServiceCategory.objects.filter(code=code).first()
        categories[code] = found or catalog_services.create_category(
            actor, code=code, name_ar=name_ar, name_en=name_en, sort_order=order
        )
    defs = _all_service_defs()
    existing = {s.code: s for s in Service.objects.filter(code__in=[d.code for d in defs])}
    for order, d in enumerate(defs, start=1):
        service = existing.get(d.code)
        if service is None:
            service = catalog_services.create_service(
                actor,
                code=d.code,
                name_ar=d.name_ar,
                name_en=d.name_en,
                kind=d.kind,
                department_id=cat.departments[d.department].pk,
                category_id=categories[d.category].pk,
                sort_order=order,
            )
            cat.count("services")
        cat.services[d.code] = service
    return defs


def _version(
    plist: PriceList, prices: dict[int, Decimal], *, actor: User, on: date, note: str, cat: Catalog
) -> None:
    if PriceListVersion.objects.filter(price_list=plist).exists():
        return
    catalog_services.create_version(
        plist, effective_from=on, prices=prices, actor=actor, note=note, today=on
    )
    cat.count("price_versions")


def _price_lists(
    cat: Catalog, defs: list[data.ServiceDef], actor: User, on: date
) -> dict[str, PriceList]:
    cash_prices = {cat.services[d.code].pk: Decimal(d.price) for d in defs}
    cash = catalog_services.default_price_list()
    _version(cash, cash_prices, actor=actor, on=on, note="Opening prices (demo)", cat=cat)
    lists = {"CASH": cash}
    for p in data.PAYERS:
        plist = PriceList.objects.filter(code=p.code).first()
        if plist is None:
            row = catalog_services.create_price_list(
                actor, code=p.code, name_ar=p.list_name_ar, name_en=p.list_name_en
            )
            plist = row.price_list
        factor = Decimal(p.price_percent) / 100
        prices = {sid: q(price * factor) for sid, price in cash_prices.items()}
        _version(plist, prices, actor=actor, on=on, note="Contract prices (demo)", cat=cat)
        lists[p.code] = plist
    return lists


def _payers(cat: Catalog, lists: dict[str, PriceList], actor: User, on: date) -> None:
    for p in data.PAYERS:
        payer = Payer.objects.filter(code=p.code).first()
        if payer is None:
            payer = catalog_services.create_payer(
                actor,
                code=p.code,
                name_ar=p.name_ar,
                name_en=p.name_en,
                kind=p.kind,
                price_list_id=lists[p.code].pk,
                contract_no=p.contract_no,
                contract_start=date(on.year, 1, 1),
                claim_period=p.claim_period,
                requires_card_number=p.requires_card_number,
                phone=p.phone,
                email=f"claims@{p.code.lower()}.example.test",
            )
            for r in p.rules:
                catalog_services.add_coverage_rule(
                    actor,
                    payer.pk,
                    rule_kind=r.rule_kind,
                    service_id=cat.services[r.service].pk if r.service else None,
                    service_kind=r.service_kind,
                    payer_percent=Decimal(r.payer_percent) if r.payer_percent is not None else None,
                    copay_amount=Decimal(r.copay) if r.copay is not None else None,
                    ceiling_amount=Decimal(r.ceiling) if r.ceiling is not None else None,
                    requires_pre_approval=r.pre_approval,
                    note=r.note,
                )
            for code in p.exclusions:
                catalog_services.add_exclusion(
                    actor,
                    payer.pk,
                    service_id=cat.services[code].pk,
                    note="Not covered by contract",
                )
            cat.count("payers")
        cat.payers[p.code] = payer


# --- pharmacy -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StockPlan:
    """Opening batches of one item: (batch no, days to expiry, pharmacy qty, main qty, cost)."""

    batches: tuple[tuple[str, int, int, int, Decimal], ...]
    min_stock: int
    reorder_qty: int


def _stock_plan(code: str, unit: str, popularity: int, price: int, rng: random.Random) -> StockPlan:
    countable = unit in ("tablet", "capsule", "piece", "pair", "sachet", "ampoule", "cartridge")
    base = {5: 3000, 4: 1600, 3: 800, 2: 300, 1: 120}[popularity]
    if not countable:
        base = max(12, base // 12)
    prefix = code[:3].upper()
    first_expiry = rng.randint(60, 420)
    second_expiry = rng.randint(480, 900)
    cost = q(Decimal(price) * Decimal("0.62"))
    early = max(10, base // 3)
    late = base
    return StockPlan(
        batches=(
            (f"{prefix}-{rng.randint(1000, 4999)}", first_expiry, early, 0, cost),
            (
                f"{prefix}-{rng.randint(5000, 9999)}",
                second_expiry,
                late,
                late,
                q(cost * Decimal("1.04")),
            ),
        ),
        min_stock=max(5, base // 4),
        reorder_qty=base,
    )


#: Items whose first batch runs out of date during the month (expiry report) or soon after.
EXPIRING: dict[str, int] = {
    "DRG-AMOX250": 12,
    "DRG-ERY250": 20,
    "DRG-CEFOTAX1G": 26,
    "DRG-ORS": 38,
    "DRG-ZINC20": 41,
    "DRG-SALB4": 45,
    "DRG-PENV250": 50,
}

#: Items opened below their minimum (low-stock list).
LOW: tuple[str, ...] = ("DRG-CEFTRI500", "DRG-HCORTINJ", "DRG-INSREG", "DRG-SSDCR", "CNS-FOLEY16")


def _pharmacy(cat: Catalog, actor: User, on: date, rng: random.Random) -> None:
    classes: dict[str, DrugClass] = {}
    for code, name_ar, name_en in data.DRUG_CLASSES:
        classes[code], _ = DrugClass.objects.update_or_create(
            code=code, defaults={"name_ar": name_ar, "name_en": name_en, "active": True}
        )
    for code, kind, dept, name_ar, name_en, dispense in data.STORES:
        cat.stores[code], _ = Store.objects.update_or_create(
            code=code,
            defaults={
                "kind": kind,
                "department": cat.departments[dept] if dept else None,
                "name_ar": name_ar,
                "name_en": name_en,
                "allows_dispense": dispense,
                "active": True,
            },
        )
    for code, name_ar, name_en in data.SUPPLIERS:
        cat.suppliers[code], _ = Supplier.objects.update_or_create(
            code=code, defaults={"name_ar": name_ar, "name_en": name_en, "active": True}
        )

    specs: list[tuple[str, str, str, str, str, int, int, int, tuple[str, ...], str]] = [
        (
            d.service_code,
            d.generic,
            d.strength,
            d.unit,
            d.form or data.FORM_OF_UNIT.get(d.unit, "other"),
            d.pack,
            d.price,
            d.popularity,
            d.classes,
            d.storage,
        )
        for d in data.DRUGS
    ] + [
        (
            s.service_code,
            s.name_en,
            s.detail,
            s.unit,
            "supply",
            s.pack,
            s.price,
            s.popularity,
            (),
            "room",
        )
        for s in data.SUPPLIES
    ]
    plans: dict[str, StockPlan] = {}
    for code, generic, strength, unit, form, pack, price, pop, cls, storage in specs:
        plan = _stock_plan(code[4:], unit, pop, price, rng)
        if code in EXPIRING:
            (b1, _, p1, m1, c1), second = plan.batches
            plan = StockPlan(
                ((b1, EXPIRING[code], p1, m1, c1), second), plan.min_stock, plan.reorder_qty
            )
        if code in LOW:
            (b1, e1, _, _, c1), (b2, e2, _, _, c2) = plan.batches
            plan = StockPlan(
                ((b1, e1, 2, 0, c1), (b2, e2, 3, 0, c2)), max(plan.min_stock, 20), plan.reorder_qty
            )
        plans[code] = plan
        item = Item.objects.filter(service=cat.services[code]).first()
        if item is None:
            unit_ar, unit_en = data.UNITS[unit]
            item = pharmacy_services.create_item(
                service=cat.services[code],
                generic_name=generic,
                base_unit_code=unit,
                base_unit_name_ar=unit_ar,
                base_unit_name_en=unit_en,
                actor=actor,
                form=form,
                strength=strength,
                min_stock=Decimal(plan.min_stock),
                reorder_qty=Decimal(plan.reorder_qty),
                storage=storage,
            )
            if unit in ("tablet", "capsule") and pack >= 20 and pack % 10 == 0:
                pharmacy_services.add_unit(
                    item, unit_code="strip", name_ar="شريط", name_en="Strip", factor=10, actor=actor
                )
            if pack > 1:
                pharmacy_services.add_unit(
                    item,
                    unit_code="box",
                    name_ar="علبة",
                    name_en="Box",
                    factor=pack,
                    actor=actor,
                    is_dispensable=unit not in ("tablet", "capsule"),
                    is_purchase_unit=True,
                )
            item.drug_classes.add(*(classes[c] for c in cls))
            cat.count("items")
        cat.items[code] = item

    for store_code, supplier_code, invoice_no in (
        ("PHA", "SUP-NILE", "DEMO-OPEN-PHA"),
        ("MAIN", "SUP-AMIN", "DEMO-OPEN-MAIN"),
    ):
        supplier = cat.suppliers[supplier_code]
        if GoodsReceipt.objects.filter(supplier=supplier, supplier_invoice_no=invoice_no).exists():
            continue
        receipt = pharmacy_services.create_receipt(
            supplier=supplier,
            store=cat.stores[store_code],
            actor=actor,
            supplier_invoice_no=invoice_no,
            supplier_invoice_date=on,
            note="Opening stock (demo)",
        )
        for code, plan in plans.items():
            for batch_no, days, pha_qty, main_qty, cost in plan.batches:
                qty = pha_qty if store_code == "PHA" else main_qty
                if qty <= 0:
                    continue
                pharmacy_services.add_receipt_line(
                    receipt,
                    item=cat.items[code],
                    batch_no=batch_no,
                    expiry_date=on + timedelta(days=days),
                    quantity=qty,
                    unit_cost=cost,
                    actor=actor,
                    today=on,
                )
        pharmacy_services.post_receipt(receipt, actor=actor, today=on)
        cat.count("receipts")


# --- laboratory and beds --------------------------------------------------------------------------


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _lab(cat: Catalog, actor: User) -> None:
    for t in data.LAB_TESTS:
        if LabTest.objects.filter(service=cat.services[t.service_code]).exists():
            continue
        test = lab_services.create_lab_test(
            service=cat.services[t.service_code],
            code=t.code,
            sample_type=t.sample_type,
            actor=actor,
            container=t.container,
            turnaround_minutes=t.turnaround,
            instructions_ar=t.instructions_ar,
            instructions_en=t.instructions_en,
        )
        for order, p in enumerate(t.params, start=1):
            param = lab_services.add_parameter(
                test,
                actor=actor,
                code=p.code,
                name_ar=p.name_ar,
                name_en=p.name_en,
                unit=p.unit,
                value_type=p.value_type,
                choices=list(p.choices) or None,
                decimals=p.decimals,
                sort_order=order,
            )
            for r in p.ranges:
                lab_services.add_reference_range(
                    param,
                    actor=actor,
                    sex=r.sex,
                    age_min_days=r.age_min_days,
                    age_max_days=r.age_max_days,
                    low=_dec(r.low),
                    high=_dec(r.high),
                    critical_low=_dec(r.critical_low),
                    critical_high=_dec(r.critical_high),
                    normal_text=r.normal_text,
                )
        cat.count("lab_tests")


def _beds(cat: Catalog, rooms: dict[str, Room], actor: User) -> None:
    for code, room, name_ar, name_en, service in data.BEDS:
        bed = Bed.objects.filter(code=code).first()
        if bed is None:
            bed = visit_services.create_bed(
                code=code,
                name_ar=name_ar,
                name_en=name_en,
                bed_service=cat.services[service],
                actor=actor,
                room=rooms[room],
            )
            cat.count("beds")
        cat.beds[code] = bed


def seed_catalog(*, on: date, rng: random.Random) -> Catalog:
    """Create or complete the demo configuration, effective from ``on``."""
    cat = Catalog()
    _center()
    _people(cat)
    admin = cat.users["admin"]
    rooms = _places(cat)
    defs = _services(cat, admin)
    _doctors(cat, rooms)
    lists = _price_lists(cat, defs, admin, on)
    _payers(cat, lists, admin, on)
    _pharmacy(cat, cat.users["pharmacist"], on, rng)
    _lab(cat, cat.users["labsup"])
    _beds(cat, rooms, admin)
    return cat
