"""Named e2e data builders, run by ``manage.py e2e_fixture <name> --params '<json>' --json``.

Each fixture builds rows through the services, as the user a real screen would act as
(``as``: a seed username), after checking the permission the matching endpoint will require.
So a fixture can never create data the application itself would refuse: the seven invariants,
the database guards and the role matrix all apply. Each run is one transaction; a refused
step leaves nothing behind.

Parameters are a JSON object. References accept an id (number) or the document's own number
or code (string): ``patient`` an id or file number, ``visit`` / ``invoice`` / ``shift`` an id
or document number, ``payer`` / ``service`` / ``department`` / ``till`` / ``bank`` / ``room``
a code, ``doctor`` and ``as`` a username. Money is a string (``"15000.00"``) or an integer,
never a float. Unknown parameters are refused (``FIXTURE_PARAM_UNKNOWN``), so a typo fails
loudly. Results are plain JSON: ids, numbers, codes, money as strings.

More fixtures can live in any app: a module ``apps/<app>/e2e_fixtures.py`` that registers
builders with :func:`fixture` is imported by the command (``autodiscover``), so a module
builder adds its own without editing this file.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import pghistory
from django.db import DatabaseError, models, transaction
from django.utils import timezone

from apps.billing import services as billing
from apps.billing.models import DocumentStatus, Invoice
from apps.catalog import services as catalog_services
from apps.catalog.models import Payer, PriceList, Service
from apps.clinical import services as clinical
from apps.clinical.models import AllergenType, Allergy, Severity
from apps.core.models import Department, DoctorProfile, Room, User
from apps.core.services import require_permission
from apps.lab.models import LabTest
from apps.orders import services as orders
from apps.orders.models import ServiceLine
from apps.patients import services as patients
from apps.patients.models import Patient, PatientCoverage, Sex
from apps.payments import services as payments
from apps.payments.models import Allocation, Bank, Payment, Shift, ShiftStatus, Till
from apps.pharmacy.models import Batch, DrugClass, Item, StockBalance, Store
from apps.visits import services as visits
from apps.visits.models import ACTIVE_QUEUE_STATUSES, Bed, QueueEntry, Visit
from domain.errors import DomainError
from domain.money import ZERO, money

__all__ = [
    "REGISTRY",
    "Fixture",
    "Params",
    "fixture",
    "run_fixture",
]

Json = dict[str, Any]


# --- registry ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Fixture:
    name: str
    summary: str
    params: frozenset[str]
    build: Callable[[Params], Json]


REGISTRY: dict[str, Fixture] = {}

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def fixture(
    name: str, *, summary: str, params: Iterable[str]
) -> Callable[[Callable[[Params], Json]], Callable[[Params], Json]]:
    """Register a builder under ``name``. ``params`` lists the accepted parameter names
    (``as`` is always accepted)."""
    if not _NAME_RE.match(name):
        raise ValueError(f"Fixture names are snake_case, got {name!r}")

    def register(build: Callable[[Params], Json]) -> Callable[[Params], Json]:
        existing = REGISTRY.get(name)
        if existing is not None and existing.build is not build:
            raise ValueError(f"Fixture {name!r} is registered twice")
        REGISTRY[name] = Fixture(name, summary, frozenset({"as", *params}), build)
        return build

    return register


def _db_error(exc: DatabaseError) -> DomainError:
    """A database guard's ``CODE: message`` as a domain error (other errors keep their text)."""
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    found = re.match(r"^([A-Z][A-Z0-9_]+): (.*)$", text)
    if found:
        return DomainError(found.group(1), found.group(2))
    return DomainError("DATABASE_ERROR", text)


def run_fixture(name: str, raw: Mapping[str, Any]) -> Json:
    """Run fixture ``name`` with ``raw`` parameters in one transaction.

    Raises:
        DomainError: ``FIXTURE_UNKNOWN``, ``FIXTURE_PARAM_UNKNOWN``, ``FIXTURE_PARAM_INVALID``,
            ``FIXTURE_REF_NOT_FOUND`` and any rule the services enforce.
        PermissionRequired: the acting user lacks the endpoint's permission.
    """
    spec = REGISTRY.get(name)
    if spec is None:
        raise DomainError("FIXTURE_UNKNOWN", f"No fixture named {name!r}", known=sorted(REGISTRY))
    unknown = sorted(set(raw) - spec.params)
    if unknown:
        raise DomainError(
            "FIXTURE_PARAM_UNKNOWN",
            f"Fixture {name!r} does not take {', '.join(unknown)}",
            unknown=unknown,
            accepted=sorted(spec.params),
        )
    try:
        with transaction.atomic(), pghistory.context(command="e2e_fixture", fixture=name):
            return spec.build(Params(raw))
    except DatabaseError as exc:
        raise _db_error(exc) from exc


# --- parameters ---------------------------------------------------------------------------------


def _invalid(key: str, message: str) -> DomainError:
    return DomainError("FIXTURE_PARAM_INVALID", f"{key}: {message}", param=key)


def _missing(kind: str, ref: object) -> DomainError:
    return DomainError("FIXTURE_REF_NOT_FOUND", f"No {kind} {ref!r}", kind=kind, ref=str(ref))


class Params:
    """Typed access to one fixture's JSON parameters."""

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self.raw = dict(raw)

    def has(self, key: str) -> bool:
        return key in self.raw and self.raw[key] is not None

    def text(self, key: str, default: str = "") -> str:
        value = self.raw.get(key, default)
        if value is None:
            return default
        if not isinstance(value, str):
            raise _invalid(key, "expected a string")
        return value

    def flag(self, key: str, default: bool = False) -> bool:
        value = self.raw.get(key, default)
        if value is None:
            return default
        if not isinstance(value, bool):
            raise _invalid(key, "expected true or false")
        return value

    def integer(self, key: str) -> int | None:
        value = self.raw.get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise _invalid(key, "expected a whole number")
        return value

    def amount(self, key: str) -> Decimal | None:
        """Money as a string or an integer (a float is refused, ARCHITECTURE 4.3)."""
        value = self.raw.get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, str | int):
            raise _invalid(key, 'expected money as a string ("15000.00") or an integer')
        return money(value)

    def number(self, key: str) -> Decimal | None:
        """A decimal quantity or percent, as a string or an integer."""
        value = self.raw.get(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, str | int):
            raise _invalid(key, "expected a number as a string or an integer")
        try:
            parsed = Decimal(str(value).strip())
        except InvalidOperation:
            raise _invalid(key, "not a number") from None
        if not parsed.is_finite():
            raise _invalid(key, "not a finite number")
        return parsed

    def day(self, key: str) -> date | None:
        value = self.raw.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise _invalid(key, "expected an ISO date (YYYY-MM-DD)")
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise _invalid(key, "expected an ISO date (YYYY-MM-DD)") from None

    def items(self, key: str) -> list[Any]:
        value = self.raw.get(key)
        if value is None:
            return []
        if not isinstance(value, list):
            raise _invalid(key, "expected a list")
        return value

    def mapping(self, key: str) -> dict[str, Any]:
        value = self.raw.get(key)
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise _invalid(key, "expected an object")
        return value

    def choice(self, key: str, allowed: Sequence[str], default: str) -> str:
        value = self.text(key, default)
        if value not in allowed:
            raise _invalid(key, f"expected one of {', '.join(allowed)}")
        return value

    # references ----------------------------------------------------------------------------

    def actor(self, default: str) -> User:
        """The acting user: parameter ``as`` (a seed username), else ``default``."""
        return self.user("as", default)

    def user(self, key: str, default: str) -> User:
        username = self.text(key, default)
        user = User.objects.filter(username=username, is_active=True).first()
        if user is None:
            raise _missing("user (run seed_e2e first)", username)
        return user

    def patient(self, key: str = "patient") -> Patient:
        ref = self.raw.get(key)
        found = _by_ref(Patient, ref, "file_no")
        if found is None:
            raise _missing("patient", ref) if ref is not None else _invalid(key, "required")
        return found

    def visit(self, key: str = "visit") -> Visit:
        ref = self.raw.get(key)
        found = _by_ref(Visit, ref, "number")
        if found is None:
            raise _missing("visit", ref) if ref is not None else _invalid(key, "required")
        return found

    def invoice(self, key: str = "invoice") -> Invoice:
        ref = self.raw.get(key)
        found = _by_ref(Invoice, ref, "number")
        if found is None:
            raise _missing("invoice", ref) if ref is not None else _invalid(key, "required")
        return found

    def shift(self, key: str = "shift") -> Shift | None:
        ref = self.raw.get(key)
        if ref is None:
            return None
        found = _by_ref(Shift, ref, "number")
        if found is None:
            raise _missing("shift", ref)
        return found

    def payer(self, key: str = "payer") -> Payer | None:
        return _code(Payer, self.raw.get(key), "payer")

    def department(self, key: str = "department") -> Department | None:
        return _code(Department, self.raw.get(key), "department")

    def room(self, key: str = "room") -> Room | None:
        return _code(Room, self.raw.get(key), "room")

    def till(self, key: str = "till") -> Till | None:
        return _code(Till, self.raw.get(key), "till")

    def bank(self, key: str = "bank") -> Bank | None:
        return _code(Bank, self.raw.get(key), "bank")

    def doctor(self, key: str = "doctor", default: str | None = None) -> DoctorProfile | None:
        username = self.raw.get(key, default)
        if username is None:
            return None
        if not isinstance(username, str):
            raise _invalid(key, "expected a username")
        found = DoctorProfile.objects.filter(user__username=username).first()
        if found is None:
            raise _missing("doctor", username)
        return found


def _by_ref[M: models.Model](model: type[M], ref: object, field: str) -> M | None:
    """``ref`` is the row's id (a number) or its natural key ``field`` (a string)."""
    if isinstance(ref, bool) or ref is None:
        return None
    if isinstance(ref, int):
        return model._default_manager.filter(pk=ref).first()
    if isinstance(ref, str) and ref.strip():
        return model._default_manager.filter(**{field: ref.strip()}).first()
    return None


def _code[M: (Payer, Department, Room, Till, Bank, DrugClass)](
    model: type[M], ref: object, kind: str
) -> M | None:
    if ref is None:
        return None
    if not isinstance(ref, str):
        raise _invalid(kind, "expected a code")
    found = model.objects.filter(code=ref).first()
    if found is None:
        raise _missing(kind, ref)
    return found


def _service(code: object) -> Service:
    if not isinstance(code, str):
        raise _invalid("service", "expected a service code")
    found = Service.objects.filter(code=code).first()
    if found is None:
        raise _missing("service", code)
    return found


# --- JSON views ---------------------------------------------------------------------------------


def _m(value: Decimal | None) -> str | None:
    return None if value is None else str(money(value))


def patient_json(p: Patient) -> Json:
    return {
        "id": p.pk,
        "file_no": p.file_no,
        "full_name_ar": p.full_name_ar,
        "full_name_en": p.full_name_en,
        "sex": p.sex,
        "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
        "phone": p.phone,
        "is_incomplete": p.is_incomplete,
    }


def coverage_json(c: PatientCoverage) -> Json:
    return {
        "id": c.pk,
        "patient_id": c.patient_id,
        "payer": c.payer.code,
        "card_number": c.card_number,
        "is_default": c.is_default,
    }


def line_json(sl: ServiceLine) -> Json:
    return {
        "id": sl.pk,
        "visit_id": sl.visit_id,
        "service": sl.service.code,
        "kind": sl.kind,
        "quantity": int(sl.quantity),
        "payer": sl.payer.code if sl.payer is not None else None,
        "billing_status": sl.billing_status,
        "fulfilment_status": sl.fulfilment_status,
        "state": str(orders.line_state(sl)),
        "order_source": sl.order_source,
    }


def _lines(visit: Visit) -> list[Json]:
    qs = ServiceLine.objects.filter(visit=visit).select_related("service", "payer").order_by("id")
    return [line_json(sl) for sl in qs]


def queue_json(entry: QueueEntry | None) -> Json | None:
    if entry is None:
        return None
    return {
        "id": entry.pk,
        "token_no": entry.token_no,
        "queue_date": entry.queue_date.isoformat(),
        "status": entry.status,
        "department": entry.department.code,
        "doctor": entry.doctor.user.username if entry.doctor is not None else None,
        "ready": visits.is_ready(entry),
    }


def visit_json(v: Visit) -> Json:
    return {
        "id": v.pk,
        "number": v.number,
        "patient_id": v.patient_id,
        "visit_type": v.visit_type,
        "status": v.status,
        "department": v.department.code if v.department is not None else None,
        "doctor": v.doctor.user.username if v.doctor is not None else None,
        "payer": v.payer.code if v.payer is not None else None,
        "card_number": v.card_number,
    }


def _visit_result(v: Visit) -> Json:
    entry = (
        QueueEntry.objects.filter(visit=v, status__in=ACTIVE_QUEUE_STATUSES)
        .select_related("department", "doctor__user")
        .first()
    )
    return {"visit": visit_json(v), "lines": _lines(v), "queue_entry": queue_json(entry)}


def invoice_json(inv: Invoice) -> Json:
    outstanding = None
    if inv.status == DocumentStatus.APPROVED:
        outstanding = _m(billing.invoice_position(inv).outstanding)
    return {
        "id": inv.pk,
        "number": inv.number,
        "status": inv.status,
        "visit_id": inv.visit_id,
        "patient_id": inv.patient_id,
        "priced_on": inv.priced_on.isoformat() if inv.priced_on else None,
        "gross_total": _m(inv.gross_total),
        "discount_total": _m(inv.discount_total),
        "payer_total": _m(inv.payer_total),
        "patient_total": _m(inv.patient_total),
        "outstanding": outstanding,
        "lines": [
            {
                "id": il.pk,
                "line_no": il.line_no,
                "service_line_id": il.service_line_id,
                "service": il.service.code,
                "quantity": int(il.quantity),
                "unit_price": _m(il.unit_price),
                "gross": _m(il.gross),
                "discount": _m(il.discount),
                "payer": il.payer.code if il.payer is not None else None,
                "payer_share": _m(il.payer_share),
                "patient_share": _m(il.patient_share),
            }
            for il in inv.lines.select_related("service", "payer").order_by("line_no")
        ],
    }


def shift_json(s: Shift) -> Json:
    expected = s.expected_cash if s.status == ShiftStatus.CLOSED else payments.expected_cash(s)
    return {
        "id": s.pk,
        "number": s.number,
        "status": s.status,
        "cashier": s.cashier.username,
        "till": s.till.code if s.till is not None else None,
        "opening_float": _m(s.opening_float),
        "expected_cash": _m(expected),
        "counted_cash": _m(s.counted_cash),
        "variance": _m(s.variance),
    }


def payment_json(p: Payment) -> Json:
    return {
        "id": p.pk,
        "number": p.number,
        "shift_id": p.shift_id,
        "patient_id": p.patient_id,
        "method": p.method,
        "amount": _m(p.amount),
        "verification": p.verification,
        "bank": p.bank.code if p.bank is not None else None,
        "reference": p.reference,
    }


# --- generated demographics ---------------------------------------------------------------------

_MALE = (
    ("محمد", "Mohamed"),
    ("أحمد", "Ahmed"),
    ("عثمان", "Osman"),
    ("عبدالله", "Abdalla"),
    ("إبراهيم", "Ibrahim"),
    ("مصطفى", "Mustafa"),
    ("حسن", "Hassan"),
    ("يوسف", "Yousif"),
    ("خالد", "Khalid"),
    ("عمر", "Omer"),
    ("صلاح", "Salah"),
    ("الطيب", "Altayeb"),
)
_FEMALE = (
    ("فاطمة", "Fatima"),
    ("آمنة", "Amna"),
    ("مريم", "Mariam"),
    ("هالة", "Hala"),
    ("سارة", "Sara"),
    ("نادية", "Nadia"),
    ("زينب", "Zainab"),
    ("رشا", "Rasha"),
    ("سلمى", "Salma"),
    ("إيمان", "Iman"),
    ("منى", "Muna"),
    ("هبة", "Hiba"),
)
_FAMILY = (
    *_MALE,
    ("الأمين", "Alamin"),
    ("بشير", "Bashir"),
    ("النور", "Alnour"),
    ("عوض", "Awad"),
    ("الفاتح", "Alfatih"),
    ("حامد", "Hamid"),
)


def _pick[T](options: Sequence[T]) -> T:
    return options[secrets.randbelow(len(options))]


def generated_person(sex: str) -> tuple[str, str]:
    """A plausible Sudanese three-part name in Arabic and English."""
    first = _pick(_FEMALE if sex == Sex.FEMALE else _MALE)
    father, grandfather = _pick(_FAMILY), _pick(_FAMILY)
    return (
        f"{first[0]} {father[0]} {grandfather[0]}",
        f"{first[1]} {father[1]} {grandfather[1]}",
    )


def generated_phone() -> str:
    """A Sudanese mobile number (``09`` + 8 digits); random, so files rarely share one."""
    return f"09{secrets.randbelow(10**8):08d}"


def _card_number(payer: Payer) -> str:
    return f"{payer.code}-{secrets.randbelow(10**6):06d}"


# --- catalog lookup -------------------------------------------------------------------------------


@fixture("catalog", summary="Ids of the seeded catalog, keyed by code (read-only).", params=())
def catalog(p: Params) -> Json:
    today = timezone.localdate()
    cash = catalog_services.default_price_list()
    try:
        cash_prices = catalog_services.version_prices(
            catalog_services.effective_version(cash, today)
        )
    except DomainError:
        cash_prices = {}
    stock: dict[tuple[int, str], int] = {}
    for batch_id, store_code, qty in StockBalance.objects.values_list(
        "batch_id", "store__code", "qty_base"
    ):
        stock[(batch_id, store_code)] = int(qty)
    stores = list(Store.objects.order_by("code"))
    return {
        "departments": {d.code: d.pk for d in Department.objects.all()},
        "rooms": {r.code: r.pk for r in Room.objects.all()},
        "doctors": {
            d.user.username: {
                "id": d.pk,
                "user_id": d.user_id,
                "department": d.department.code,
                "consultation_service": (
                    d.consultation_service.code if d.consultation_service is not None else None
                ),
            }
            for d in DoctorProfile.objects.select_related(
                "user", "department", "consultation_service"
            )
        },
        "services": {
            s.code: {
                "id": s.pk,
                "kind": s.kind,
                "department": s.department.code if s.department is not None else None,
                "name_ar": s.name_ar,
                "name_en": s.name_en,
                "cash_price": _m(cash_prices.get(s.pk)),
            }
            for s in Service.objects.select_related("department")
        },
        "price_lists": {pl.code: pl.pk for pl in PriceList.objects.all()},
        "payers": {
            py.code: {
                "id": py.pk,
                "kind": py.kind,
                "price_list": py.price_list.code if py.price_list is not None else None,
                "requires_card_number": py.requires_card_number,
            }
            for py in Payer.objects.select_related("price_list")
        },
        "stores": {s.code: s.pk for s in stores},
        "items": {
            item.service.code: {
                "id": item.pk,
                "base_unit": item.base_unit_code,
                "units": {u.unit_code: int(u.factor) for u in item.units.all()},
                "batches": [
                    {
                        "id": b.pk,
                        "batch_no": b.batch_no,
                        "expiry_date": b.expiry_date.isoformat(),
                        "stock": {s.code: stock.get((b.pk, s.code), 0) for s in stores},
                    }
                    for b in Batch.objects.filter(item=item).order_by("expiry_date", "id")
                ],
            }
            for item in Item.objects.select_related("service").prefetch_related("units")
        },
        "lab_tests": {t.service.code: t.pk for t in LabTest.objects.select_related("service")},
        "beds": {b.code: {"id": b.pk, "status": b.status} for b in Bed.objects.all()},
        "tills": {t.code: t.pk for t in Till.objects.all()},
        "banks": {b.code: b.pk for b in Bank.objects.all()},
    }


# --- patients -----------------------------------------------------------------------------------

_PATIENT_FIELDS = (
    "full_name_ar",
    "full_name_en",
    "sex",
    "date_of_birth",
    "age_years",
    "phone",
    "phone_alt",
    "address",
    "national_id",
    "emergency_contact_name",
    "emergency_contact_phone",
    "notes",
)
_COVERAGE_FIELDS = ("card_number", "valid_from", "valid_to", "patient_percent_override")


_ALLERGY_KEYS = {"drug_class", "substance", "allergen_type", "severity", "reaction"}


def allergy_json(a: Allergy) -> Json:
    return {
        "id": a.pk,
        "allergen_type": a.allergen_type,
        "drug_class": a.drug_class.code if a.drug_class is not None else None,
        "substance": a.substance,
        "severity": a.severity,
    }


def _record_allergies(p: Params, patient: Patient) -> list[Json]:
    """``allergies``: drug class codes (``"PENICILLIN"``) or objects with ``drug_class`` or
    ``substance`` (and ``allergen_type``, ``severity``, ``reaction``), recorded as
    ``allergies_as`` (default ``nurse``)."""
    entries = p.items("allergies")
    if not entries:
        return []
    actor = p.user("allergies_as", "nurse")
    require_permission(actor, "clinical.manage_allergies")
    out: list[Json] = []
    for index, raw in enumerate(entries):
        spec = {"drug_class": raw} if isinstance(raw, str) else raw
        if not isinstance(spec, dict) or set(spec) - _ALLERGY_KEYS:
            raise _invalid(f"allergies[{index}]", "a drug class code or an allergy object")
        entry = Params(spec)
        drug_class = _code(DrugClass, spec.get("drug_class"), "drug_class")
        default_type = AllergenType.DRUG_CLASS if drug_class is not None else AllergenType.OTHER
        allergy = clinical.record_allergy(
            patient,
            actor=actor,
            allergen_type=entry.text("allergen_type", default_type),
            drug_class=drug_class,
            substance=entry.text("substance"),
            reaction=entry.text("reaction"),
            severity=entry.text("severity", Severity.SEVERE),
        )
        out.append(allergy_json(allergy))
    return out


def _add_coverage(p: Params, patient: Patient, payer: Payer, actor: User) -> PatientCoverage:
    require_permission(actor, "patients.manage_coverage")
    card = p.text("card_number") or (_card_number(payer) if payer.requires_card_number else "")
    return patients.add_coverage(
        patient,
        payer=payer,
        actor=actor,
        card_number=card,
        valid_from=p.day("valid_from"),
        valid_to=p.day("valid_to"),
        patient_percent_override=p.number("patient_percent_override"),
        is_default=p.flag("is_default", True),
    )


@fixture(
    "patient",
    summary=(
        "Register a patient (generated Sudanese name and phone unless given); with `payer`, "
        "also put that payer's coverage on file; `allergies` (drug class codes or objects) "
        "are recorded by `allergies_as` (default `nurse`). As `reception`."
    ),
    params=(
        *_PATIENT_FIELDS,
        "confirm_not_duplicate",
        "emergency",
        "payer",
        *_COVERAGE_FIELDS,
        "allergies",
        "allergies_as",
    ),
)
def patient(p: Params) -> Json:
    actor = p.actor("reception")
    sex = p.choice("sex", [Sex.MALE, Sex.FEMALE, Sex.UNKNOWN], _pick([Sex.MALE, Sex.FEMALE]))
    name_ar, name_en = p.text("full_name_ar"), p.text("full_name_en")
    if not name_ar and not name_en:
        name_ar, name_en = generated_person(sex)
    age = p.integer("age_years")
    dob = p.day("date_of_birth")
    if dob is None and age is None:
        dob = timezone.localdate() - timedelta(days=365 + secrets.randbelow(70 * 365))
    phone = p.text("phone", generated_phone())
    if p.flag("emergency"):
        require_permission(actor, "patients.register_emergency")
        created = patients.register_emergency(
            name=name_ar or name_en, sex=sex, actor=actor, age_years=age, phone=phone
        )
    else:
        require_permission(actor, "patients.create")
        created = patients.register_patient(
            patients.PatientData(
                sex=sex,
                full_name_ar=name_ar,
                full_name_en=name_en,
                date_of_birth=dob,
                age_years=age,
                phone=phone,
                phone_alt=p.text("phone_alt"),
                address=p.text("address"),
                national_id=p.text("national_id"),
                emergency_contact_name=p.text("emergency_contact_name"),
                emergency_contact_phone=p.text("emergency_contact_phone"),
                notes=p.text("notes"),
            ),
            actor=actor,
            confirm_not_duplicate=p.flag("confirm_not_duplicate", True),
        )
    payer = p.payer()
    coverage = _add_coverage(p, created, payer, actor) if payer is not None else None
    return {
        "patient": patient_json(created),
        "coverage": coverage_json(coverage) if coverage is not None else None,
        "allergies": _record_allergies(p, created),
    }


@fixture(
    "coverage",
    summary="Put a payer's coverage on a patient's file. As `reception`.",
    params=("patient", "payer", "is_default", *_COVERAGE_FIELDS),
)
def coverage(p: Params) -> Json:
    actor = p.actor("reception")
    payer = p.payer()
    if payer is None:
        raise _invalid("payer", "required")
    return {"coverage": coverage_json(_add_coverage(p, p.patient(), payer, actor))}


# --- visits and orders --------------------------------------------------------------------------


@fixture(
    "visit",
    summary=(
        "Open a visit (consultation fee line and queue token included). `doctor` defaults to "
        "`doctor` (null for none); `coverage` is `default`, `cash` or a payer code on file. "
        "As `reception`."
    ),
    params=(
        "patient",
        "doctor",
        "department",
        "visit_type",
        "coverage",
        "card_number",
        "chief_complaint",
        "room",
    ),
)
def visit(p: Params) -> Json:
    actor = p.actor("reception")
    require_permission(actor, "visits.create")
    patient_row = p.patient()
    mode = p.text("coverage", "default")
    coverage_row: PatientCoverage | None = None
    if mode not in ("default", "cash"):
        payer = _code(Payer, mode, "coverage")
        coverage_row = patients.active_coverage(patient_row, payer=payer)
        if coverage_row is None:
            raise _missing("coverage on file for payer", mode)
    created = visits.create_visit(
        patient=patient_row,
        actor=actor,
        doctor=p.doctor(default="doctor"),
        department=p.department(),
        visit_type=p.text("visit_type", "new"),
        coverage=coverage_row,
        use_default_coverage=mode == "default",
        card_number=p.text("card_number"),
        chief_complaint=p.text("chief_complaint"),
        room=p.room(),
    )
    return _visit_result(created)


_ITEM_KEYS = {"service", "quantity", "note", "pre_approval_ref", "prescription"}
_DECIMAL_RX = ("dose_quantity", "frequency_per_day")


def _order_item(raw: object, index: int) -> dict[str, Any]:
    key = f"items[{index}]"
    if not isinstance(raw, dict):
        raise _invalid(key, "expected an object")
    unknown = sorted(set(raw) - _ITEM_KEYS)
    if unknown:
        raise DomainError(
            "FIXTURE_PARAM_UNKNOWN", f"{key} does not take {', '.join(unknown)}", unknown=unknown
        )
    item = Params(raw)
    out: dict[str, Any] = {"service": _service(raw.get("service"))}
    prescription = item.mapping("prescription") if item.has("prescription") else None
    if prescription is not None:
        rx = Params(prescription)
        fixed = dict(prescription)
        for name in _DECIMAL_RX:
            if rx.has(name):
                fixed[name] = rx.number(name)
        out["prescription"] = fixed
    quantity = item.number("quantity")
    if quantity is None and prescription is not None:
        detail: dict[str, Any] = out["prescription"]
        if all(detail.get(k) is not None for k in (*_DECIMAL_RX, "duration_days")):
            quantity = Decimal(
                clinical.prescription_quantity(
                    dose_quantity=detail["dose_quantity"],
                    frequency_per_day=detail["frequency_per_day"],
                    duration_days=int(detail["duration_days"]),
                )
            )
    if quantity is not None:
        out["quantity"] = quantity
    if item.has("note"):
        out["note"] = item.text("note")
    if item.has("pre_approval_ref"):
        out["pre_approval_ref"] = item.text("pre_approval_ref")
    return out


@fixture(
    "order",
    summary=(
        "Order services on an open visit after the allergy check: `items` = "
        "[{service, quantity?, note?, pre_approval_ref?, prescription?}]. A prescription with "
        "dose_quantity, frequency_per_day and duration_days sets the quantity. As `doctor`."
    ),
    params=("visit", "items", "acknowledge_allergies"),
)
def order(p: Params) -> Json:
    actor = p.actor("doctor")
    require_permission(actor, "orders.create")
    target = p.visit()
    items = [_order_item(raw, i) for i, raw in enumerate(p.items("items"))]
    created = clinical.order_lines(
        target, items, actor=actor, acknowledge_allergies=p.flag("acknowledge_allergies")
    )
    ids = [line.pk for line in created]
    qs = ServiceLine.objects.filter(pk__in=ids).select_related("service", "payer").order_by("id")
    return {"lines": [line_json(sl) for sl in qs]}


# --- invoices -----------------------------------------------------------------------------------


def _selected_lines(p: Params, target: Visit) -> list[int] | None:
    ids = p.items("lines")
    codes = p.items("services")
    if ids and codes:
        raise _invalid("lines", "give lines or services, not both")
    if ids:
        if not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
            raise _invalid("lines", "expected service line ids")
        return [int(i) for i in ids]
    if codes:
        wanted = [_service(c).pk for c in codes]
        found = list(
            billing.unbilled_lines(target)
            .filter(service_id__in=wanted)
            .values_list("id", flat=True)
        )
        if not found:
            raise _invalid("services", "no unbilled line of these services on the visit")
        return found
    return None


def _create_invoice(p: Params, actor: User, *, approve: bool) -> Invoice:
    require_permission(actor, "billing.create_invoice")
    target = p.visit()
    draft = billing.create_draft_invoice(target, actor, line_ids=_selected_lines(p, target))
    if not approve:
        return draft
    require_permission(actor, "billing.approve_invoice")
    return billing.approve_invoice(draft, actor=actor)


def _invoice_result(inv: Invoice) -> Json:
    inv.refresh_from_db()
    return {"invoice": invoice_json(inv), "lines": _lines(inv.visit)}


@fixture(
    "invoice",
    summary=(
        "Draft an invoice from a visit's unbilled lines (all, or `lines` ids, or `services` "
        "codes); `approve: true` approves it too. As `cashier`."
    ),
    params=("visit", "lines", "services", "approve"),
)
def invoice(p: Params) -> Json:
    actor = p.actor("cashier")
    return _invoice_result(_create_invoice(p, actor, approve=p.flag("approve")))


@fixture(
    "approve_invoice",
    summary=(
        "Approve a draft `invoice`, or draft and approve a `visit`'s unbilled lines (all, or "
        "`lines` / `services`). Prices freeze from today's list. As `cashier`."
    ),
    params=("invoice", "visit", "lines", "services"),
)
def approve_invoice(p: Params) -> Json:
    actor = p.actor("cashier")
    if p.has("invoice") == p.has("visit"):
        raise _invalid("invoice", "give exactly one of invoice or visit")
    if p.has("invoice"):
        require_permission(actor, "billing.approve_invoice")
        return _invoice_result(billing.approve_invoice(p.invoice(), actor=actor))
    return _invoice_result(_create_invoice(p, actor, approve=True))


# --- shifts and payments --------------------------------------------------------------------------


def _open_shift(actor: User, opening_float: Decimal, till: Till | None, note: str) -> Shift:
    require_permission(actor, "payments.open_shift")
    return payments.open_shift(actor, opening_float, till=till, note=note)


def _close(shift: Shift, actor: User, counted: Decimal | None, reason: str, note: str) -> Shift:
    require_permission(actor, "payments.close_shift")
    count = payments.expected_cash(shift) if counted is None else counted
    return payments.close_shift(shift, count, actor=actor, reason=reason or None, note=note)


@fixture(
    "open_shift",
    summary=(
        "Open the cashier's shift with `opening_float` (default 0). `if_open`: `error` "
        "(default), `reuse` the open shift, or `close` it at its expected cash first. "
        "As `cashier`."
    ),
    params=("opening_float", "till", "note", "if_open"),
)
def open_shift(p: Params) -> Json:
    actor = p.actor("cashier")
    if_open = p.choice("if_open", ["error", "reuse", "close"], "error")
    current = payments.current_shift(actor)
    if current is not None and if_open == "reuse":
        return {"shift": shift_json(current)}
    if current is not None and if_open == "close":
        _close(current, actor, None, "", "")
    opened = _open_shift(actor, p.amount("opening_float") or ZERO, p.till(), p.text("note"))
    return {"shift": shift_json(opened)}


@fixture(
    "close_shift",
    summary=(
        "Close a shift (default: the actor's open one) with `counted` cash (default: the "
        "expected cash, no variance); a variance needs `reason` (and `note`). As `cashier`."
    ),
    params=("shift", "counted", "reason", "note"),
)
def close_shift(p: Params) -> Json:
    actor = p.actor("cashier")
    target = p.shift() or payments.current_shift(actor)
    if target is None:
        raise DomainError("SHIFT_NOT_OPEN", "The user has no open shift", user=actor.username)
    closed = _close(target, actor, p.amount("counted"), p.text("reason"), p.text("note"))
    return {"shift": shift_json(closed)}


def _outstanding(inv: Invoice) -> Decimal:
    if inv.status != DocumentStatus.APPROVED:
        raise DomainError(
            "INVOICE_NOT_APPROVED", "Only an approved invoice is paid", invoice=inv.pk
        )
    return billing.invoice_position(inv).outstanding


def _plan(
    targets: Sequence[Invoice], amount: Decimal | None
) -> tuple[Decimal, list[tuple[Invoice, Decimal]]]:
    """Allocations that pay ``targets`` oldest first with ``amount`` (default: all they owe)."""
    owed = [(inv, _outstanding(inv)) for inv in targets]
    total = sum((o for _, o in owed), ZERO)
    pay = total if amount is None else amount
    left = pay
    plan: list[tuple[Invoice, Decimal]] = []
    for inv, due in owed:
        part = min(due, left)
        if part > 0:
            plan.append((inv, part))
            left -= part
    return pay, plan


@fixture(
    "pay",
    summary=(
        "Take a payment in the cashier's open shift (opened with a zero float when missing, "
        "unless `open_shift: false`) for one `invoice`, a `visit`'s approved invoices, or a "
        "`patient` (oldest open invoices first). `amount` defaults to what is owed; "
        "`allocate: none` leaves it as credit. Transfers default to bank BOK and a fresh "
        "reference. As `cashier`."
    ),
    params=(
        "invoice",
        "visit",
        "patient",
        "amount",
        "method",
        "bank",
        "reference",
        "sender_name",
        "transfer_date",
        "allocate",
        "open_shift",
        "note",
    ),
)
def pay(p: Params) -> Json:
    actor = p.actor("cashier")
    require_permission(actor, "payments.take_payment")
    if sum(p.has(k) for k in ("invoice", "visit", "patient")) != 1:
        raise _invalid("invoice", "give exactly one of invoice, visit or patient")
    method = p.text("method", "cash")
    allocate = p.choice("allocate", ["auto", "none"], "auto")
    amount = p.amount("amount")
    plan: list[tuple[Invoice, Decimal]] = []
    auto = False
    if p.has("invoice") or p.has("visit"):
        if p.has("invoice"):
            targets = [p.invoice()]
        else:
            targets = list(
                Invoice.objects.filter(visit=p.visit(), status=DocumentStatus.APPROVED).order_by(
                    "approved_at", "id"
                )
            )
        if not targets:
            raise _invalid("visit", "the visit has no approved invoice")
        patient_row = targets[0].patient
        amount, plan = _plan(targets, amount)
        if allocate == "none":
            plan = []
    else:
        patient_row = p.patient()
        if amount is None:
            amount = sum((pos.outstanding for _, pos in billing.open_invoices(patient_row)), ZERO)
        auto = allocate == "auto"
    if amount <= 0:
        raise _invalid("amount", "nothing is owed; give a positive amount")

    shift = payments.current_shift(actor)
    if shift is None and p.flag("open_shift", True):
        shift = _open_shift(actor, ZERO, None, "")
    if shift is None:
        raise DomainError("SHIFT_NOT_OPEN", "Open a shift first")

    bank = p.bank()
    reference = p.text("reference")
    if method != "cash" and method != "patient_credit":
        bank = bank or Bank.objects.get(code="BOK")
        reference = reference or f"E2E{secrets.token_hex(5).upper()}"
    payment = payments.record_payment(
        shift,
        patient_row,
        method,
        amount,
        actor=actor,
        bank=bank,
        reference=reference,
        transfer_date=p.day("transfer_date"),
        sender_name=p.text("sender_name"),
        allocations=plan or None,
        auto=auto,
        note=p.text("note"),
    )
    allocations = list(
        Allocation.objects.filter(payment=payment).select_related("invoice").order_by("id")
    )
    touched = sorted({a.invoice_id for a in allocations} | {inv.pk for inv, _ in plan})
    invoices = list(Invoice.objects.filter(pk__in=touched).order_by("id"))
    line_qs = (
        ServiceLine.objects.filter(invoice_lines__invoice__in=invoices)
        .select_related("service", "payer")
        .distinct()
        .order_by("id")
    )
    shift.refresh_from_db()
    return {
        "payment": payment_json(payment),
        "allocations": [{"invoice_id": a.invoice_id, "amount": _m(a.amount)} for a in allocations],
        "invoices": [invoice_json(inv) for inv in invoices],
        "lines": [line_json(sl) for sl in line_qs],
        "shift": shift_json(shift),
    }


# --- compound -----------------------------------------------------------------------------------

_VISIT_KEYS = ("doctor", "department", "visit_type", "coverage", "card_number", "chief_complaint")


@fixture(
    "paid_visit",
    summary=(
        "A patient (existing `patient`, or a new one from `patient_fields`) with a visit whose "
        "consultation fee is invoiced and paid in cash, so it waits ready in the doctor's "
        "queue. Acts as `reception` then `cashier` (`cashier_as`)."
    ),
    params=("patient", "patient_fields", *_VISIT_KEYS, "method", "cashier_as"),
)
def paid_visit(p: Params) -> Json:
    reception = p.text("as", "reception")
    cashier = p.text("cashier_as", "cashier")
    if p.has("patient") and p.has("patient_fields"):
        raise _invalid("patient", "give patient or patient_fields, not both")
    if p.has("patient"):
        person = p.patient()
        made: Json = {"patient": patient_json(person), "coverage": None, "allergies": []}
    else:
        fields = p.mapping("patient_fields")
        made = run_nested("patient", {**fields, "as": reception})
    visit_params = {k: p.raw[k] for k in _VISIT_KEYS if p.has(k)}
    opened = run_nested(
        "visit", {**visit_params, "patient": made["patient"]["id"], "as": reception}
    )
    result: Json = {**made, **opened, "invoice": None, "payment": None, "shift": None}
    if not any(line["billing_status"] == "unbilled" for line in opened["lines"]):
        return result  # a free follow-up: nothing to pay
    vid = opened["visit"]["id"]
    approved = run_nested("approve_invoice", {"visit": vid, "as": cashier})
    paid = run_nested("pay", {"visit": vid, "method": p.text("method", "cash"), "as": cashier})
    queued = _visit_result(Visit.objects.get(pk=vid))
    result.update(
        {
            "invoice": paid["invoices"][0] if paid["invoices"] else approved["invoice"],
            "payment": paid["payment"],
            "shift": paid["shift"],
            "lines": queued["lines"],
            "queue_entry": queued["queue_entry"],
        }
    )
    return result


def run_nested(name: str, raw: Mapping[str, Any]) -> Json:
    """Run another fixture inside the current one (same transaction, same checks)."""
    spec = REGISTRY[name]
    unknown = sorted(set(raw) - spec.params)
    if unknown:
        raise DomainError(
            "FIXTURE_PARAM_UNKNOWN",
            f"Fixture {name!r} does not take {', '.join(unknown)}",
            unknown=unknown,
        )
    return spec.build(Params(raw))
