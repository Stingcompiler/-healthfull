"""The e2e base catalog: a small, realistic Sudanese outpatient center (``seed_e2e``).

What it creates, every row keyed by a stable code so specs can find it:

* Departments, clinic rooms, three wards (rooms of the ``WRD`` department) with nine beds.
* Four doctors with weekly schedules and a consultation fee service each: the ``doctor`` role
  user (general practice) and three more doctor accounts (``pediatrician``, ``gynecologist``,
  ``dentist``, see ``EXTRA_DOCTORS``).
* Services of every kind (consultation, lab, procedure, drug, consumable, bed) in Arabic and
  English, grouped in categories.
* The default cash price list and one contract list per payer, each with a version effective
  from the day of the first seed; the cash list also has a +10% version scheduled for the
  first day of next month (FEATURES 5.2).
* Three payers with different coverage rules (FEATURES 5.5-5.8): ``AMAN`` pays 70% (and needs
  a pre-approval for the obstetric ultrasound, and excludes dental fillings), ``NAKHEEL``
  leaves a fixed 2,000 SDG copay per line, ``RAHMA`` pays up to a 10,000 SDG ceiling per line.
* Drugs and consumables with their unit hierarchy (box, strip, tablet), two batches each with
  different expiries, received through posted goods receipts into the pharmacy and the main
  store. Amoxicillin and ORS have a batch expiring within 30 days; ceftriaxone is below its
  minimum stock.
* Lab tests with parameters and reference ranges by sex and age.
* Tills, banks (seeded by migration, re-activated here) and the default reason codes.

Rows are created through the services where one exists (price list versions, stock items and
units, goods receipts, lab tests and ranges, beds) and written directly only for plain
configuration that has no service yet (departments, rooms, services, payers, rules,
schedules). Running the seed again creates nothing twice: configuration rows are put back to
the seed values, and dated or posted documents (price versions, receipts) are created only
when missing. Batch expiries are relative to the day of the first seed.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from decimal import Decimal
from typing import Any

import pghistory
from django.utils import timezone

from apps.catalog import services as catalog_services
from apps.catalog.models import (
    ClaimPeriod,
    CoverageRule,
    CoverageRuleKind,
    Exclusion,
    Payer,
    PayerKind,
    PriceList,
    PriceListKind,
    PriceListVersion,
    Service,
    ServiceCategory,
    ServiceKind,
)
from apps.core.models import Department, DoctorProfile, ReasonCode, Room, User
from apps.core.reason_codes import REASON_CODES, ensure_reason_codes
from apps.lab import services as lab_services
from apps.lab.models import LabParameter, LabTest, RangeSex, SampleType, ValueType
from apps.payments.models import Bank, Till
from apps.pharmacy import services as pharmacy_services
from apps.pharmacy.models import (
    DosageForm,
    DrugClass,
    GoodsReceipt,
    Item,
    ReceiptStatus,
    Storage,
    Store,
    StoreKind,
    Supplier,
    UnitConversion,
)
from apps.visits import services as visit_services
from apps.visits.models import Bed, BedStatus, DoctorSchedule
from domain.errors import DomainError
from domain.money import q

# --- departments, rooms, wards ----------------------------------------------------------------

#: (code, name_ar, name_en), in display order.
DEPARTMENTS: tuple[tuple[str, str, str], ...] = (
    ("GEN", "الطب العام", "General Medicine"),
    ("PED", "طب الأطفال", "Pediatrics"),
    ("GYN", "النساء والتوليد", "Gynecology"),
    ("DEN", "الأسنان", "Dental"),
    ("LAB", "المعمل", "Laboratory"),
    ("PHA", "الصيدلية", "Pharmacy"),
    ("PRC", "الإجراءات والتمريض", "Procedures and Nursing"),
    ("ER", "الطوارئ", "Emergency"),
    ("WRD", "القسم الداخلي", "Inpatient Ward"),
)

#: (code, department, name_ar, name_en). ``WRD-*`` rooms are the wards.
ROOMS: tuple[tuple[str, str, str, str], ...] = (
    ("GEN-1", "GEN", "عيادة الطب العام 1", "General clinic 1"),
    ("GEN-2", "GEN", "عيادة الطب العام 2", "General clinic 2"),
    ("PED-1", "PED", "عيادة الأطفال", "Pediatrics clinic"),
    ("GYN-1", "GYN", "عيادة النساء والتوليد", "Gynecology clinic"),
    ("DEN-1", "DEN", "عيادة الأسنان", "Dental clinic"),
    ("LAB-1", "LAB", "غرفة سحب العينات", "Sample collection room"),
    ("PRC-1", "PRC", "غرفة الإجراءات", "Procedure room"),
    ("ER-1", "ER", "غرفة الطوارئ", "Emergency room"),
    ("WRD-M", "WRD", "عنبر الرجال", "Men's ward"),
    ("WRD-F", "WRD", "عنبر النساء", "Women's ward"),
    ("WRD-P", "WRD", "الغرفة الخاصة", "Private room"),
)


@dataclass(frozen=True, slots=True)
class BedDef:
    code: str
    room: str
    name_ar: str
    name_en: str
    service: str
    status: str = BedStatus.AVAILABLE


BEDS: tuple[BedDef, ...] = (
    *(
        BedDef(f"M-0{n}", "WRD-M", f"عنبر الرجال - سرير {n}", f"Men's ward, bed {n}", "BED-WARD")
        for n in range(1, 5)
    ),
    *(
        BedDef(
            f"F-0{n}",
            "WRD-F",
            f"عنبر النساء - سرير {n}",
            f"Women's ward, bed {n}",
            "BED-WARD",
            BedStatus.MAINTENANCE if n == 4 else BedStatus.AVAILABLE,
        )
        for n in range(1, 5)
    ),
    BedDef("P-01", "WRD-P", "الغرفة الخاصة - سرير 1", "Private room, bed 1", "BED-PRIV"),
)

# --- doctors and schedules --------------------------------------------------------------------

# Weekdays as stored by DoctorSchedule: 0 = Monday ... 6 = Sunday. Friday (4) is the weekend.
SAT, SUN, MON, TUE, WED, THU, FRI = 5, 6, 0, 1, 2, 3, 4


@dataclass(frozen=True, slots=True)
class SessionDef:
    weekdays: tuple[int, ...]
    start: time
    end: time
    slot_minutes: int
    room: str


@dataclass(frozen=True, slots=True)
class DoctorDef:
    username: str
    full_name_ar: str
    full_name_en: str
    department: str
    specialty_ar: str
    specialty_en: str
    consultation: str
    sessions: tuple[SessionDef, ...]


#: Doctor accounts besides the ``doctor`` role user (same test password, role ``doctor``).
EXTRA_DOCTORS: tuple[DoctorDef, ...] = (
    DoctorDef(
        "pediatrician",
        "د. فاطمة الزين",
        "Dr. Fatima Alzain",
        "PED",
        "طب الأطفال",
        "Pediatrics",
        "CONS-PED",
        (
            SessionDef((SUN, TUE, THU), time(9), time(13), 20, "PED-1"),
            SessionDef((SAT,), time(17), time(21), 20, "PED-1"),
        ),
    ),
    DoctorDef(
        "gynecologist",
        "د. سلمى عوض",
        "Dr. Salma Awad",
        "GYN",
        "النساء والتوليد",
        "Obstetrics and gynecology",
        "CONS-GYN",
        (SessionDef((SAT, MON, WED), time(10), time(14), 30, "GYN-1"),),
    ),
    DoctorDef(
        "dentist",
        "د. ياسر النور",
        "Dr. Yasir Alnour",
        "DEN",
        "طب الأسنان",
        "Dentistry",
        "CONS-DEN",
        (SessionDef((SUN, MON, TUE, WED, THU), time(16), time(20), 30, "DEN-1"),),
    ),
)

#: The ``doctor`` role user's clinic profile (general practice, every day of the week).
GENERAL_DOCTOR = DoctorDef(
    "doctor",
    "د. أحمد الطيب",
    "Dr. Ahmed Altayeb",
    "GEN",
    "طب عام",
    "General practice",
    "CONS-GEN",
    (
        SessionDef((SAT, SUN, MON, TUE, WED, THU), time(8), time(14), 15, "GEN-1"),
        SessionDef((FRI,), time(16), time(20), 15, "GEN-1"),
    ),
)

# --- services ---------------------------------------------------------------------------------

#: (code, name_ar, name_en).
CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("CONS", "الكشوفات", "Consultations"),
    ("HEM", "أمراض الدم", "Hematology"),
    ("CHEM", "الكيمياء الحيوية", "Clinical chemistry"),
    ("MICRO", "الأحياء الدقيقة والطفيليات", "Microbiology and parasitology"),
    ("PROC", "الإجراءات", "Procedures"),
    ("DENT", "إجراءات الأسنان", "Dental procedures"),
    ("DRUG", "الأدوية", "Medicines"),
    ("SUPPLY", "المستهلكات الطبية", "Medical supplies"),
    ("BED", "الإقامة", "Accommodation"),
)


@dataclass(frozen=True, slots=True)
class ServiceDef:
    code: str
    kind: str
    department: str
    category: str
    name_ar: str
    name_en: str
    #: Cash price per unit (per base unit for drugs and consumables), SDG.
    price: str


_C, _L, _P = ServiceKind.CONSULTATION, ServiceKind.LAB, ServiceKind.PROCEDURE
_D, _S, _B = ServiceKind.DRUG, ServiceKind.CONSUMABLE, ServiceKind.BED

SERVICES: tuple[ServiceDef, ...] = (
    # Consultations: the fee line a visit with the doctor creates (FEATURES 2.2).
    ServiceDef("CONS-GEN", _C, "GEN", "CONS", "كشف طب عام", "General consultation", "15000"),
    ServiceDef("CONS-PED", _C, "PED", "CONS", "كشف أطفال", "Pediatric consultation", "20000"),
    ServiceDef(
        "CONS-GYN", _C, "GYN", "CONS", "كشف نساء وتوليد", "Gynecology consultation", "25000"
    ),
    ServiceDef("CONS-DEN", _C, "DEN", "CONS", "كشف أسنان", "Dental consultation", "15000"),
    ServiceDef("CONS-ER", _C, "ER", "CONS", "كشف طوارئ", "Emergency consultation", "20000"),
    # Laboratory.
    ServiceDef(
        "LAB-CBC", _L, "LAB", "HEM", "صورة الدم الكاملة", "Complete blood count (CBC)", "12000"
    ),
    ServiceDef(
        "LAB-BFMP", _L, "LAB", "MICRO", "فحص الملاريا (شريحة دم)", "Blood film for malaria", "5000"
    ),
    ServiceDef("LAB-FBS", _L, "LAB", "CHEM", "سكر الدم الصائم", "Fasting blood sugar", "4000"),
    ServiceDef("LAB-RBS", _L, "LAB", "CHEM", "سكر الدم العشوائي", "Random blood sugar", "3500"),
    ServiceDef(
        "LAB-RFT",
        _L,
        "LAB",
        "CHEM",
        "وظائف الكلى (يوريا وكرياتينين)",
        "Renal function (urea, creatinine)",
        "9000",
    ),
    ServiceDef("LAB-UA", _L, "LAB", "MICRO", "فحص البول العام", "Urinalysis", "5000"),
    # Procedures and nursing.
    ServiceDef("PRC-INJ", _P, "PRC", "PROC", "حقنة عضلية", "Intramuscular injection", "2000"),
    ServiceDef("PRC-CANNULA", _P, "PRC", "PROC", "تركيب كانيولا", "IV cannula insertion", "3000"),
    ServiceDef("PRC-DRESS", _P, "PRC", "PROC", "غيار جرح", "Wound dressing", "5000"),
    ServiceDef("PRC-SUTURE", _P, "PRC", "PROC", "خياطة جرح", "Wound suturing", "15000"),
    ServiceDef("PRC-NEB", _P, "PRC", "PROC", "جلسة بخار (نيبولايزر)", "Nebulizer session", "4000"),
    ServiceDef("PRC-ECG", _P, "PRC", "PROC", "تخطيط القلب", "Electrocardiogram (ECG)", "10000"),
    ServiceDef("GYN-US", _P, "GYN", "PROC", "موجات صوتية للحمل", "Obstetric ultrasound", "20000"),
    ServiceDef("DEN-EXT", _P, "DEN", "DENT", "خلع سن", "Tooth extraction", "25000"),
    ServiceDef("DEN-FILL", _P, "DEN", "DENT", "حشوة سن", "Tooth filling", "30000"),
    # Drugs (price per base unit: tablet, capsule, vial, bottle, sachet).
    ServiceDef(
        "DRG-PARA500",
        _D,
        "PHA",
        "DRUG",
        "باراسيتامول 500 ملغ أقراص",
        "Paracetamol 500 mg tablets",
        "50",
    ),
    ServiceDef(
        "DRG-AMOX500",
        _D,
        "PHA",
        "DRUG",
        "أموكسيسيلين 500 ملغ كبسولات",
        "Amoxicillin 500 mg capsules",
        "300",
    ),
    ServiceDef(
        "DRG-IBU400",
        _D,
        "PHA",
        "DRUG",
        "إيبوبروفين 400 ملغ أقراص",
        "Ibuprofen 400 mg tablets",
        "100",
    ),
    ServiceDef(
        "DRG-COART",
        _D,
        "PHA",
        "DRUG",
        "أرتيميثر ولوميفانترين 20/120 ملغ أقراص",
        "Artemether/lumefantrine 20/120 mg tablets",
        "500",
    ),
    ServiceDef(
        "DRG-METRO500",
        _D,
        "PHA",
        "DRUG",
        "ميترونيدازول 500 ملغ أقراص",
        "Metronidazole 500 mg tablets",
        "150",
    ),
    ServiceDef(
        "DRG-CEFTRI1G",
        _D,
        "PHA",
        "DRUG",
        "سيفترياكسون 1 غ حقنة",
        "Ceftriaxone 1 g injection",
        "3500",
    ),
    ServiceDef(
        "DRG-PARASYR",
        _D,
        "PHA",
        "DRUG",
        "باراسيتامول شراب 120 ملغ/5 مل",
        "Paracetamol syrup 120 mg/5 ml",
        "1500",
    ),
    ServiceDef(
        "DRG-ORS", _D, "PHA", "DRUG", "أملاح الإرواء الفموي", "Oral rehydration salts", "300"
    ),
    # Consumables.
    ServiceDef("CNS-SYR5", _S, "PHA", "SUPPLY", "حقنة 5 مل", "Syringe 5 ml", "200"),
    ServiceDef("CNS-CANNULA20", _S, "PHA", "SUPPLY", "كانيولا 20G", "IV cannula 20G", "1500"),
    ServiceDef("CNS-GAUZE", _S, "PHA", "SUPPLY", "شاش معقم", "Sterile gauze pack", "500"),
    ServiceDef(
        "CNS-GLOVES", _S, "PHA", "SUPPLY", "قفازات فحص (زوج)", "Examination gloves (pair)", "300"
    ),
    # Bed days (minimal inpatient, FEATURES 10.5).
    ServiceDef("BED-WARD", _B, "WRD", "BED", "إقامة يومية - عنبر", "Ward bed day", "30000"),
    ServiceDef(
        "BED-PRIV", _B, "WRD", "BED", "إقامة يومية - غرفة خاصة", "Private room bed day", "60000"
    ),
)

# --- price lists and payers -------------------------------------------------------------------

CASH_LIST = "CASH"
#: Bulk change of the cash list's scheduled version (from the 1st of next month).
SCHEDULED_CASH_INCREASE = Decimal(10)


@dataclass(frozen=True, slots=True)
class RuleDef:
    rule_kind: str
    service: str | None = None
    service_kind: str = ""
    payer_percent: str | None = None
    copay: str | None = None
    ceiling: str | None = None
    pre_approval: bool = False
    note: str = ""


@dataclass(frozen=True, slots=True)
class PayerDef:
    code: str
    kind: str
    name_ar: str
    name_en: str
    list_name_ar: str
    list_name_en: str
    #: Contract price = cash price x factor.
    price_factor: str
    requires_card_number: bool
    claim_period: str
    contract_no: str
    phone: str
    rules: tuple[RuleDef, ...]
    #: Service codes the payer never covers (100% patient, FEATURES 5.7).
    exclusions: tuple[str, ...] = ()


PAYERS: tuple[PayerDef, ...] = (
    PayerDef(
        "AMAN",
        PayerKind.INSURANCE,
        "شركة الأمان للتأمين الصحي (تجريبية)",
        "Al-Aman Health Insurance (test)",
        "أسعار الأمان للتأمين",
        "Al-Aman insurance prices",
        "0.90",
        True,
        ClaimPeriod.MONTHLY,
        "AMN-2026-001",
        "+249 912 000 101",
        (
            RuleDef(CoverageRuleKind.PERCENTAGE, payer_percent="70", note="70% of every line"),
            RuleDef(
                CoverageRuleKind.PERCENTAGE,
                service="GYN-US",
                payer_percent="70",
                pre_approval=True,
                note="Pre-approval reference required",
            ),
        ),
        exclusions=("DEN-FILL",),
    ),
    PayerDef(
        "NAKHEEL",
        PayerKind.COMPANY,
        "شركة النخيل للاتصالات (تجريبية)",
        "Nakheel Telecom (test)",
        "أسعار شركة النخيل",
        "Nakheel Telecom prices",
        "1.00",
        True,
        ClaimPeriod.MONTHLY,
        "NKL-2026-014",
        "+249 912 000 102",
        (RuleDef(CoverageRuleKind.COPAY, copay="2000", note="Employee pays 2,000 per line"),),
    ),
    PayerDef(
        "RAHMA",
        PayerKind.NGO,
        "منظمة الرحمة الخيرية (تجريبية)",
        "Rahma Charity (test)",
        "أسعار منظمة الرحمة",
        "Rahma Charity prices",
        "0.80",
        False,
        ClaimPeriod.QUARTERLY,
        "RHM-2026-003",
        "+249 912 000 103",
        (
            RuleDef(
                CoverageRuleKind.CEILING,
                payer_percent="100",
                ceiling="10000",
                note="Up to 10,000 per line",
            ),
        ),
    ),
)

# --- pharmacy ---------------------------------------------------------------------------------

#: (code, name_ar, name_en).
DRUG_CLASSES: tuple[tuple[str, str, str], ...] = (
    ("PENICILLIN", "البنسلينات", "Penicillins"),
    ("CEPHALOSPORIN", "السيفالوسبورينات", "Cephalosporins"),
    ("NSAID", "مضادات الالتهاب غير الستيرويدية", "NSAIDs"),
)

#: (code, kind, department, name_ar, name_en, allows_dispense).
STORES: tuple[tuple[str, str, str | None, str, str, bool], ...] = (
    ("MAIN", StoreKind.MAIN, None, "المخزن الرئيسي", "Main store", False),
    ("PHA", StoreKind.PHARMACY, "PHA", "الصيدلية الخارجية", "Outpatient pharmacy", True),
)

#: (code, name_ar, name_en).
SUPPLIERS: tuple[tuple[str, str, str], ...] = (
    ("SUP-MED", "شركة الإمداد الطبي (تجريبية)", "Medical Supply Co. (test)"),
    ("SUP-KDD", "مستودع الخرطوم للأدوية (تجريبي)", "Khartoum Drug Depot (test)"),
)

#: The opening goods receipts: (store, supplier, supplier invoice number).
RECEIPTS: tuple[tuple[str, str, str], ...] = (
    ("PHA", "SUP-MED", "SEED-PHA-0001"),
    ("MAIN", "SUP-KDD", "SEED-MAIN-0001"),
)


@dataclass(frozen=True, slots=True)
class BatchDef:
    batch_no: str
    #: Expiry = day of the first seed + this many days.
    expires_in_days: int
    #: Base units received into the pharmacy and the main store.
    pharmacy_qty: int
    main_qty: int
    #: Cost per base unit.
    unit_cost: str


@dataclass(frozen=True, slots=True)
class UnitDef:
    code: str
    name_ar: str
    name_en: str
    factor: int
    purchase: bool = False
    dispensable: bool = True


@dataclass(frozen=True, slots=True)
class ItemDef:
    service: str
    generic_name: str
    form: str
    strength: str
    base: tuple[str, str, str]
    units: tuple[UnitDef, ...]
    min_stock: int
    reorder_qty: int
    batches: tuple[BatchDef, BatchDef]
    storage: str = Storage.ROOM
    classes: tuple[str, ...] = ()
    brand_name: str = ""


_TAB = ("tablet", "قرص", "Tablet")
_STRIP10 = UnitDef("strip", "شريط", "Strip", 10)


def _box(factor: int) -> UnitDef:
    return UnitDef("box", "علبة", "Box", factor, purchase=True)


ITEMS: tuple[ItemDef, ...] = (
    ItemDef(
        "DRG-PARA500",
        "Paracetamol",
        DosageForm.TABLET,
        "500 mg",
        _TAB,
        (_STRIP10, _box(100)),
        200,
        1000,
        (BatchDef("PCM-1101", 75, 300, 0, "30"), BatchDef("PCM-1207", 540, 1000, 2000, "32")),
    ),
    ItemDef(
        "DRG-AMOX500",
        "Amoxicillin",
        DosageForm.CAPSULE,
        "500 mg",
        ("capsule", "كبسولة", "Capsule"),
        (_STRIP10, _box(20)),
        100,
        400,
        (BatchDef("AMX-2203", 20, 40, 0, "180"), BatchDef("AMX-2311", 600, 200, 400, "190")),
        classes=("PENICILLIN",),
    ),
    ItemDef(
        "DRG-IBU400",
        "Ibuprofen",
        DosageForm.TABLET,
        "400 mg",
        _TAB,
        (_STRIP10, _box(30)),
        90,
        300,
        (BatchDef("IBU-3105", 120, 150, 0, "60"), BatchDef("IBU-3209", 700, 300, 600, "62")),
        classes=("NSAID",),
    ),
    ItemDef(
        "DRG-COART",
        "Artemether/Lumefantrine",
        DosageForm.TABLET,
        "20/120 mg",
        _TAB,
        (UnitDef("box", "علبة", "Box", 24, purchase=True),),
        48,
        240,
        (BatchDef("COA-4102", 90, 48, 0, "300"), BatchDef("COA-4210", 500, 240, 480, "310")),
    ),
    ItemDef(
        "DRG-METRO500",
        "Metronidazole",
        DosageForm.TABLET,
        "500 mg",
        _TAB,
        (_STRIP10, _box(20)),
        60,
        200,
        (BatchDef("MTZ-5104", 60, 100, 0, "80"), BatchDef("MTZ-5208", 650, 200, 400, "85")),
    ),
    ItemDef(
        "DRG-CEFTRI1G",
        "Ceftriaxone",
        DosageForm.INJECTION,
        "1 g",
        ("vial", "قارورة", "Vial"),
        (_box(10),),
        20,
        50,
        (BatchDef("CEF-6106", 150, 5, 0, "2000"), BatchDef("CEF-6212", 720, 3, 0, "2100")),
        classes=("CEPHALOSPORIN",),
    ),
    ItemDef(
        "DRG-PARASYR",
        "Paracetamol",
        DosageForm.SYRUP,
        "120 mg/5 ml, 60 ml",
        ("bottle", "زجاجة", "Bottle"),
        (_box(12),),
        12,
        48,
        (BatchDef("PSY-7103", 45, 12, 0, "900"), BatchDef("PSY-7207", 480, 24, 48, "950")),
    ),
    ItemDef(
        "DRG-ORS",
        "Oral rehydration salts",
        DosageForm.SACHET,
        "20.5 g",
        ("sachet", "كيس", "Sachet"),
        (_box(50),),
        50,
        200,
        (BatchDef("ORS-8101", 25, 30, 0, "150"), BatchDef("ORS-8206", 400, 100, 200, "160")),
    ),
    ItemDef(
        "CNS-SYR5",
        "Syringe",
        DosageForm.SUPPLY,
        "5 ml",
        ("piece", "قطعة", "Piece"),
        (_box(100),),
        100,
        500,
        (BatchDef("SYR-9110", 300, 100, 0, "100"), BatchDef("SYR-9301", 900, 300, 1000, "110")),
    ),
    ItemDef(
        "CNS-CANNULA20",
        "IV cannula",
        DosageForm.SUPPLY,
        "20G",
        ("piece", "قطعة", "Piece"),
        (_box(50),),
        30,
        100,
        (BatchDef("CAN-9207", 200, 20, 0, "900"), BatchDef("CAN-9405", 800, 50, 100, "950")),
    ),
    ItemDef(
        "CNS-GAUZE",
        "Sterile gauze",
        DosageForm.SUPPLY,
        "10 x 10 cm",
        ("pack", "عبوة", "Pack"),
        (_box(50),),
        30,
        100,
        (BatchDef("GAU-9309", 250, 30, 0, "250"), BatchDef("GAU-9503", 850, 50, 100, "260")),
    ),
    ItemDef(
        "CNS-GLOVES",
        "Examination gloves",
        DosageForm.SUPPLY,
        "Medium",
        ("pair", "زوج", "Pair"),
        (_box(50),),
        50,
        200,
        (BatchDef("GLV-9408", 220, 50, 0, "150"), BatchDef("GLV-9602", 820, 100, 200, "160")),
    ),
)

# --- laboratory ------------------------------------------------------------------------------

ADULT_DAYS = 18 * 365


@dataclass(frozen=True, slots=True)
class RangeDef:
    sex: str = RangeSex.ANY
    age_min_days: int = 0
    age_max_days: int | None = None
    low: str | None = None
    high: str | None = None
    critical_low: str | None = None
    critical_high: str | None = None
    normal_text: str = ""


@dataclass(frozen=True, slots=True)
class ParamDef:
    code: str
    name_ar: str
    name_en: str
    unit: str
    value_type: str
    decimals: int
    ranges: tuple[RangeDef, ...]
    choices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LabTestDef:
    service: str
    code: str
    sample_type: str
    container: str
    turnaround_minutes: int
    params: tuple[ParamDef, ...]
    instructions_ar: str = ""
    instructions_en: str = ""


_N, _T, _CH, _PN = ValueType.NUMERIC, ValueType.TEXT, ValueType.CHOICE, ValueType.POS_NEG
_GRADES = ("nil", "trace", "1+", "2+", "3+")
_GLUCOSE = RangeDef(low="70", high="100", critical_low="40", critical_high="400")

LAB_TESTS: tuple[LabTestDef, ...] = (
    LabTestDef(
        "LAB-CBC",
        "CBC",
        SampleType.WHOLE_BLOOD,
        "EDTA",
        60,
        (
            ParamDef(
                "WBC",
                "كريات الدم البيضاء",
                "White blood cells",
                "10^9/L",
                _N,
                1,
                (RangeDef(low="4.0", high="11.0", critical_low="2.0", critical_high="30.0"),),
            ),
            ParamDef(
                "HGB",
                "الهيموغلوبين",
                "Hemoglobin",
                "g/dL",
                _N,
                1,
                (
                    RangeDef(
                        age_max_days=ADULT_DAYS,
                        low="11.0",
                        high="14.5",
                        critical_low="7.0",
                        critical_high="20.0",
                    ),
                    RangeDef(
                        sex=RangeSex.MALE,
                        age_min_days=ADULT_DAYS,
                        low="13.0",
                        high="17.0",
                        critical_low="7.0",
                        critical_high="20.0",
                    ),
                    RangeDef(
                        sex=RangeSex.FEMALE,
                        age_min_days=ADULT_DAYS,
                        low="12.0",
                        high="15.5",
                        critical_low="7.0",
                        critical_high="20.0",
                    ),
                ),
            ),
            ParamDef(
                "PLT",
                "الصفائح الدموية",
                "Platelets",
                "10^9/L",
                _N,
                0,
                (RangeDef(low="150", high="450", critical_low="50", critical_high="1000"),),
            ),
        ),
    ),
    LabTestDef(
        "LAB-BFMP",
        "BFMP",
        SampleType.WHOLE_BLOOD,
        "EDTA",
        30,
        (
            ParamDef(
                "MP",
                "طفيل الملاريا",
                "Malaria parasites",
                "",
                _PN,
                0,
                (RangeDef(normal_text="negative"),),
            ),
        ),
    ),
    LabTestDef(
        "LAB-FBS",
        "FBS",
        SampleType.PLASMA,
        "Fluoride",
        30,
        (ParamDef("GLU", "الجلوكوز", "Glucose", "mg/dL", _N, 0, (_GLUCOSE,)),),
        instructions_ar="صيام 8 ساعات على الأقل",
        instructions_en="Fast for at least 8 hours",
    ),
    LabTestDef(
        "LAB-RBS",
        "RBS",
        SampleType.PLASMA,
        "Fluoride",
        30,
        (
            ParamDef(
                "GLU",
                "الجلوكوز",
                "Glucose",
                "mg/dL",
                _N,
                0,
                (RangeDef(low="70", high="140", critical_low="40", critical_high="400"),),
            ),
        ),
    ),
    LabTestDef(
        "LAB-RFT",
        "RFT",
        SampleType.SERUM,
        "Plain",
        120,
        (
            ParamDef(
                "UREA",
                "اليوريا",
                "Urea",
                "mg/dL",
                _N,
                0,
                (RangeDef(low="15", high="45", critical_high="200"),),
            ),
            ParamDef(
                "CREAT",
                "الكرياتينين",
                "Creatinine",
                "mg/dL",
                _N,
                2,
                (
                    RangeDef(low="0.60", high="1.30", critical_high="10.00"),
                    RangeDef(sex=RangeSex.MALE, low="0.70", high="1.30", critical_high="10.00"),
                    RangeDef(sex=RangeSex.FEMALE, low="0.60", high="1.10", critical_high="10.00"),
                ),
            ),
        ),
    ),
    LabTestDef(
        "LAB-UA",
        "UA",
        SampleType.URINE,
        "Sterile container",
        45,
        (
            ParamDef("COLOR", "اللون", "Colour", "", _T, 0, (RangeDef(normal_text="yellow"),)),
            ParamDef("PH", "الأس الهيدروجيني", "pH", "", _N, 1, (RangeDef(low="4.5", high="8.0"),)),
            ParamDef(
                "PROT", "البروتين", "Protein", "", _CH, 0, (RangeDef(normal_text="nil"),), _GRADES
            ),
            ParamDef(
                "GLU", "السكر", "Glucose", "", _CH, 0, (RangeDef(normal_text="nil"),), _GRADES
            ),
            ParamDef("PUS", "خلايا الصديد", "Pus cells", "/HPF", _N, 0, (RangeDef(high="5"),)),
        ),
        instructions_ar="عينة منتصف البول الصباحية",
        instructions_en="Early-morning midstream sample",
    ),
)

#: Banks seeded by ``payments.0002``; a seed run makes them usable again.
SEEDED_BANKS: tuple[str, ...] = ("BOK", "FIB", "ONB", "OTHER")

#: (code, name_ar, name_en).
TILLS: tuple[tuple[str, str, str], ...] = (
    ("T1", "الصندوق 1", "Till 1"),
    ("T2", "الصندوق 2", "Till 2"),
)


# --- seeding ----------------------------------------------------------------------------------


@dataclass(slots=True)
class CatalogSummary:
    """What the catalog seed holds after a run (and what it created this time)."""

    services: int = 0
    price_lists: int = 0
    payers: int = 0
    items: int = 0
    lab_tests: int = 0
    beds: int = 0
    created_versions: int = 0
    created_receipts: int = 0
    notes: list[str] = field(default_factory=list)


def _first_of_next_month(on: date) -> date:
    days = calendar.monthrange(on.year, on.month)[1]
    return on.replace(day=1) + timedelta(days=days)


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def seed_departments() -> dict[str, Department]:
    result: dict[str, Department] = {}
    for order, (code, name_ar, name_en) in enumerate(DEPARTMENTS, start=1):
        dept, _ = Department.objects.update_or_create(
            code=code,
            defaults={"name_ar": name_ar, "name_en": name_en, "active": True, "sort_order": order},
        )
        result[code] = dept
    return result


def _seed_rooms(departments: dict[str, Department]) -> dict[str, Room]:
    rooms: dict[str, Room] = {}
    for code, dept, name_ar, name_en in ROOMS:
        rooms[code], _ = Room.objects.update_or_create(
            code=code,
            defaults={
                "department": departments[dept],
                "name_ar": name_ar,
                "name_en": name_en,
                "active": True,
            },
        )
    return rooms


def _seed_services(departments: dict[str, Department]) -> dict[str, Service]:
    categories: dict[str, ServiceCategory] = {}
    for order, (code, name_ar, name_en) in enumerate(CATEGORIES, start=1):
        categories[code], _ = ServiceCategory.objects.update_or_create(
            code=code,
            defaults={"name_ar": name_ar, "name_en": name_en, "sort_order": order, "active": True},
        )
    services: dict[str, Service] = {}
    for order, s in enumerate(SERVICES, start=1):
        services[s.code], _ = Service.objects.update_or_create(
            code=s.code,
            defaults={
                "name_ar": s.name_ar,
                "name_en": s.name_en,
                "kind": s.kind,
                "department": departments[s.department],
                "category": categories[s.category],
                "active": True,
                "sort_order": order,
            },
        )
    return services


def _seed_versions(
    price_list: PriceList,
    prices: dict[int, Decimal],
    *,
    actor: User,
    today: date,
    summary: CatalogSummary,
) -> None:
    """The list's first version, effective today, when it has none yet."""
    versions = PriceListVersion.objects.filter(price_list=price_list)
    if not versions.exists():
        catalog_services.create_version(
            price_list,
            effective_from=today,
            prices=prices,
            actor=actor,
            note="Opening prices (e2e seed)",
            today=today,
        )
        summary.created_versions += 1
        return
    try:
        current = catalog_services.effective_version(price_list, today)
    except DomainError:
        summary.notes.append(f"price list {price_list.code}: no version is effective today")
        return
    missing = sorted(set(prices) - set(catalog_services.version_prices(current)))
    if missing:
        summary.notes.append(
            f"price list {price_list.code}: {len(missing)} seed service(s) have no price in "
            "the effective version (reset the database to re-seed prices)"
        )


def _seed_price_lists(
    services: dict[str, Service], *, actor: User, today: date, summary: CatalogSummary
) -> dict[str, PriceList]:
    cash_prices = {services[s.code].pk: Decimal(s.price) for s in SERVICES}
    cash = PriceList.objects.get(code=CASH_LIST)  # seeded by catalog.0002
    _seed_versions(cash, cash_prices, actor=actor, today=today, summary=summary)
    # Only next to the opening version: a long-lived dev database re-seeded every month must
    # not gain a new +10% version each time the previous one starts.
    if PriceListVersion.objects.filter(price_list=cash).count() == 1:
        catalog_services.bulk_percentage_update(
            cash,
            percent=SCHEDULED_CASH_INCREASE,
            effective_from=_first_of_next_month(today),
            actor=actor,
            note="Scheduled price increase (e2e seed)",
            today=today,
        )
        summary.created_versions += 1
    lists = {CASH_LIST: cash}
    for p in PAYERS:
        plist, _ = PriceList.objects.update_or_create(
            code=p.code,
            defaults={
                "name_ar": p.list_name_ar,
                "name_en": p.list_name_en,
                "kind": PriceListKind.PAYER,
                "is_default": False,
                "active": True,
            },
        )
        factor = Decimal(p.price_factor)
        prices = {sid: q(price * factor) for sid, price in cash_prices.items()}
        _seed_versions(plist, prices, actor=actor, today=today, summary=summary)
        lists[p.code] = plist
    return lists


def _seed_payers(
    services: dict[str, Service], lists: dict[str, PriceList], *, today: date
) -> dict[str, Payer]:
    payers: dict[str, Payer] = {}
    for p in PAYERS:
        payer, _ = Payer.objects.update_or_create(
            code=p.code,
            defaults={
                "name_ar": p.name_ar,
                "name_en": p.name_en,
                "kind": p.kind,
                "price_list": lists[p.code],
                "contract_no": p.contract_no,
                "contract_start": date(today.year, 1, 1),
                "contract_end": None,
                "claim_period": p.claim_period,
                "requires_card_number": p.requires_card_number,
                "contact_name": "",
                "phone": p.phone,
                "email": f"claims@{p.code.lower()}.example.test",
                "active": True,
            },
        )
        payers[p.code] = payer
        wanted: set[int] = set()
        for r in p.rules:
            service = services[r.service] if r.service else None
            rule = CoverageRule.objects.filter(
                payer=payer, service=service, service_kind=r.service_kind, active=True
            ).first() or CoverageRule(payer=payer, service=service, service_kind=r.service_kind)
            rule.rule_kind = r.rule_kind
            rule.payer_percent = _dec(r.payer_percent)
            rule.copay_amount = _dec(r.copay)
            rule.ceiling_amount = _dec(r.ceiling)
            rule.requires_pre_approval = r.pre_approval
            rule.active = True
            rule.note = r.note
            rule.save()
            wanted.add(rule.pk)
        # Rules an e2e spec added are switched off, so the seed rules decide every split.
        CoverageRule.objects.filter(payer=payer, active=True).exclude(pk__in=wanted).update(
            active=False
        )
        for code in p.exclusions:
            Exclusion.objects.update_or_create(
                payer=payer,
                service=services[code],
                defaults={"service_kind": "", "active": True, "note": "Not covered by contract"},
            )
    return payers


def _seed_doctor(
    user: User,
    spec: DoctorDef,
    *,
    departments: dict[str, Department],
    rooms: dict[str, Room],
    services: dict[str, Service],
) -> DoctorProfile:
    profile, _ = DoctorProfile.objects.update_or_create(
        user=user,
        defaults={
            "department": departments[spec.department],
            "specialty_ar": spec.specialty_ar,
            "specialty_en": spec.specialty_en,
            "consultation_service": services[spec.consultation],
            "active": True,
        },
    )
    for session in spec.sessions:
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
    return profile


def _seed_stock(
    services: dict[str, Service],
    departments: dict[str, Department],
    *,
    actor: User,
    today: date,
    summary: CatalogSummary,
) -> None:
    classes: dict[str, DrugClass] = {}
    for code, name_ar, name_en in DRUG_CLASSES:
        classes[code], _ = DrugClass.objects.update_or_create(
            code=code, defaults={"name_ar": name_ar, "name_en": name_en, "active": True}
        )
    stores: dict[str, Store] = {}
    for code, kind, dept, name_ar, name_en, dispense in STORES:
        stores[code], _ = Store.objects.update_or_create(
            code=code,
            defaults={
                "kind": kind,
                "department": departments[dept] if dept else None,
                "name_ar": name_ar,
                "name_en": name_en,
                "allows_dispense": dispense,
                "active": True,
            },
        )
    suppliers: dict[str, Supplier] = {}
    for code, name_ar, name_en in SUPPLIERS:
        suppliers[code], _ = Supplier.objects.update_or_create(
            code=code, defaults={"name_ar": name_ar, "name_en": name_en, "active": True}
        )
    items: dict[str, Item] = {}
    for spec in ITEMS:
        service = services[spec.service]
        item = Item.objects.filter(service=service).first()
        if item is None:
            item = pharmacy_services.create_item(
                service=service,
                generic_name=spec.generic_name,
                base_unit_code=spec.base[0],
                base_unit_name_ar=spec.base[1],
                base_unit_name_en=spec.base[2],
                actor=actor,
                brand_name=spec.brand_name,
                form=spec.form,
                strength=spec.strength,
                min_stock=Decimal(spec.min_stock),
                reorder_qty=Decimal(spec.reorder_qty),
                storage=spec.storage,
            )
        for unit in spec.units:
            if not UnitConversion.objects.filter(item=item, unit_code=unit.code).exists():
                pharmacy_services.add_unit(
                    item,
                    unit_code=unit.code,
                    name_ar=unit.name_ar,
                    name_en=unit.name_en,
                    factor=unit.factor,
                    actor=actor,
                    is_dispensable=unit.dispensable,
                    is_purchase_unit=unit.purchase,
                )
        item.drug_classes.add(*(classes[c] for c in spec.classes))
        items[spec.service] = item

    for store_code, supplier_code, invoice_no in RECEIPTS:
        supplier = suppliers[supplier_code]
        if GoodsReceipt.objects.filter(
            supplier=supplier, supplier_invoice_no=invoice_no, status=ReceiptStatus.POSTED
        ).exists():
            continue
        receipt = pharmacy_services.create_receipt(
            supplier=supplier,
            store=stores[store_code],
            actor=actor,
            supplier_invoice_no=invoice_no,
            supplier_invoice_date=today,
            note="Opening stock (e2e seed)",
        )
        for spec in ITEMS:
            for batch in spec.batches:
                qty = batch.pharmacy_qty if store_code == "PHA" else batch.main_qty
                if qty <= 0:
                    continue
                pharmacy_services.add_receipt_line(
                    receipt,
                    item=items[spec.service],
                    batch_no=batch.batch_no,
                    expiry_date=today + timedelta(days=batch.expires_in_days),
                    quantity=qty,
                    unit_cost=Decimal(batch.unit_cost),
                    actor=actor,
                    today=today,
                )
        pharmacy_services.post_receipt(receipt, actor=actor, today=today)
        summary.created_receipts += 1


def _seed_lab(services: dict[str, Service], *, actor: User) -> None:
    for spec in LAB_TESTS:
        fields: dict[str, Any] = {
            "container": spec.container,
            "turnaround_minutes": spec.turnaround_minutes,
            "instructions_ar": spec.instructions_ar,
            "instructions_en": spec.instructions_en,
            "active": True,
        }
        test = LabTest.objects.filter(service=services[spec.service]).first()
        if test is None:
            test = lab_services.create_lab_test(
                service=services[spec.service],
                code=spec.code,
                sample_type=spec.sample_type,
                actor=actor,
                **fields,
            )
        else:
            for key, value in fields.items():
                setattr(test, key, value)
            test.save()
        for order, p in enumerate(spec.params, start=1):
            param, _ = LabParameter.objects.update_or_create(
                test=test,
                code=p.code,
                defaults={
                    "name_ar": p.name_ar,
                    "name_en": p.name_en,
                    "unit": p.unit,
                    "value_type": p.value_type,
                    "choices": list(p.choices),
                    "decimals": p.decimals,
                    "sort_order": order,
                    "active": True,
                },
            )
            if param.reference_ranges.exists():
                continue
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


def _seed_beds(services: dict[str, Service], rooms: dict[str, Room], *, actor: User) -> None:
    for spec in BEDS:
        bed = Bed.objects.filter(code=spec.code).first()
        if bed is None:
            bed = visit_services.create_bed(
                code=spec.code,
                name_ar=spec.name_ar,
                name_en=spec.name_en,
                bed_service=services[spec.service],
                actor=actor,
                room=rooms[spec.room],
            )
            if spec.status != BedStatus.AVAILABLE:
                bed.status = spec.status
                bed.save(update_fields=["status"])
        # An existing bed keeps its status: an e2e admission may occupy it.


def _seed_money_reference() -> None:
    for code, name_ar, name_en in TILLS:
        Till.objects.update_or_create(
            code=code, defaults={"name_ar": name_ar, "name_en": name_en, "active": True}
        )
    Bank.objects.filter(code__in=SEEDED_BANKS, active=False).update(active=True)
    ensure_reason_codes()
    # Specs may switch default reasons off; every default is active again after a seed.
    for reason in REASON_CODES:
        ReasonCode.objects.filter(category=reason.category, code=reason.code, active=False).update(
            active=True
        )


def seed_catalog(
    *,
    actor: User,
    doctors: dict[str, User],
    departments: dict[str, Department],
    today: date | None = None,
) -> CatalogSummary:
    """Create or repair the base catalog (see the module docstring). Runs inside the caller's
    transaction; ``doctors`` maps each username of :data:`GENERAL_DOCTOR` and
    :data:`EXTRA_DOCTORS` to its user."""
    on = today or timezone.localdate()
    summary = CatalogSummary()
    with pghistory.context(user=actor.pk, reason="e2e catalog seed"):
        rooms = _seed_rooms(departments)
        services = _seed_services(departments)
        lists = _seed_price_lists(services, actor=actor, today=on, summary=summary)
        _seed_payers(services, lists, today=on)
        for spec in (GENERAL_DOCTOR, *EXTRA_DOCTORS):
            _seed_doctor(
                doctors[spec.username],
                spec,
                departments=departments,
                rooms=rooms,
                services=services,
            )
        _seed_stock(services, departments, actor=actor, today=on, summary=summary)
        _seed_lab(services, actor=actor)
        _seed_beds(services, rooms, actor=actor)
        _seed_money_reference()
    summary.services = len(SERVICES)
    summary.price_lists = len(lists)
    summary.payers = len(PAYERS)
    summary.items = len(ITEMS)
    summary.lab_tests = len(LAB_TESTS)
    summary.beds = len(BEDS)
    return summary
