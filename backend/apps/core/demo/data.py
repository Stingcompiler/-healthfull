"""Reference data of the demo center: departments, doctors, services, payers, drugs, lab tests.

Plain definitions only (no database access); ``catalog`` writes them. Prices are SDG per unit
(per base unit for drugs and consumables). Names of payers and the center are invented and
marked as demo data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

# Weekdays as stored by DoctorSchedule: 0 = Monday ... 6 = Sunday. Friday (4) is the weekend.
SAT, SUN, MON, TUE, WED, THU, FRI = 5, 6, 0, 1, 2, 3, 4

CENTER = {
    "name_ar": "مركز الشفاء الطبي التخصصي (بيانات تجريبية)",
    "name_en": "Al-Shifa Specialist Medical Center (demo data)",
    "address": "أم درمان، شارع الأربعين، السودان",
    "phone": "+249 900 100 200",
    "registration_no": "DEMO-2026-001",
}

#: The five clinical departments, then the service units the clinics send work to.
CLINICAL_DEPARTMENTS: tuple[tuple[str, str, str], ...] = (
    ("GEN", "الطب العام", "General Medicine"),
    ("INT", "الباطنية", "Internal Medicine"),
    ("PED", "طب الأطفال", "Pediatrics"),
    ("GYN", "النساء والتوليد", "Obstetrics and Gynecology"),
    ("DEN", "الأسنان", "Dental"),
)
SERVICE_UNITS: tuple[tuple[str, str, str], ...] = (
    ("LAB", "المعمل", "Laboratory"),
    ("PHA", "الصيدلية", "Pharmacy"),
    ("PRC", "الإجراءات والتمريض", "Procedures and Nursing"),
    ("WRD", "القسم الداخلي", "Inpatient Ward"),
)

#: (code, department, name_ar, name_en).
ROOMS: tuple[tuple[str, str, str, str], ...] = (
    ("GEN-1", "GEN", "عيادة الطب العام 1", "General clinic 1"),
    ("GEN-2", "GEN", "عيادة الطب العام 2", "General clinic 2"),
    ("INT-1", "INT", "عيادة الباطنية 1", "Internal medicine clinic 1"),
    ("INT-2", "INT", "عيادة الباطنية 2", "Internal medicine clinic 2"),
    ("PED-1", "PED", "عيادة الأطفال 1", "Pediatrics clinic 1"),
    ("PED-2", "PED", "عيادة الأطفال 2", "Pediatrics clinic 2"),
    ("GYN-1", "GYN", "عيادة النساء 1", "Gynecology clinic 1"),
    ("GYN-2", "GYN", "عيادة النساء 2", "Gynecology clinic 2"),
    ("DEN-1", "DEN", "عيادة الأسنان 1", "Dental clinic 1"),
    ("DEN-2", "DEN", "عيادة الأسنان 2", "Dental clinic 2"),
    ("LAB-1", "LAB", "غرفة سحب العينات", "Sample collection room"),
    ("PRC-1", "PRC", "غرفة الإجراءات", "Procedure room"),
    ("WRD-M", "WRD", "عنبر الرجال", "Men's ward"),
    ("WRD-F", "WRD", "عنبر النساء", "Women's ward"),
    ("WRD-P", "WRD", "الغرفة الخاصة", "Private room"),
)

#: (code, room, name_ar, name_en, bed service).
BEDS: tuple[tuple[str, str, str, str, str], ...] = (
    *(
        (f"M-0{n}", "WRD-M", f"عنبر الرجال - سرير {n}", f"Men's ward, bed {n}", "BED-WARD")
        for n in range(1, 5)
    ),
    *(
        (f"F-0{n}", "WRD-F", f"عنبر النساء - سرير {n}", f"Women's ward, bed {n}", "BED-WARD")
        for n in range(1, 5)
    ),
    ("P-01", "WRD-P", "الغرفة الخاصة - سرير 1", "Private room, bed 1", "BED-PRIV"),
)


@dataclass(frozen=True, slots=True)
class Session:
    weekdays: tuple[int, ...]
    start: time
    end: time
    slot_minutes: int
    room: str


@dataclass(frozen=True, slots=True)
class Doctor:
    username: str
    full_name_ar: str
    full_name_en: str
    department: str
    specialty_ar: str
    specialty_en: str
    consultation: str
    sessions: tuple[Session, ...]


_WEEK = (SAT, SUN, MON, TUE, WED, THU)

DOCTORS: tuple[Doctor, ...] = (
    Doctor(
        "dr.hamid",
        "د. عمر حامد الأمين",
        "Dr. Omer Hamid Alamin",
        "GEN",
        "طب عام",
        "General practice",
        "CONS-GEN",
        (Session(_WEEK, time(8), time(14), 15, "GEN-1"),),
    ),
    Doctor(
        "dr.alnour",
        "د. مها النور عثمان",
        "Dr. Maha Alnour Osman",
        "GEN",
        "طب عام",
        "General practice",
        "CONS-GEN",
        (
            Session(_WEEK, time(14), time(20), 15, "GEN-2"),
            Session((FRI,), time(16), time(20), 15, "GEN-2"),
        ),
    ),
    Doctor(
        "dr.kabbashi",
        "د. خالد الكباشي",
        "Dr. Khalid Alkabbashi",
        "INT",
        "استشاري الباطنية",
        "Consultant physician",
        "CONS-INT",
        (Session((SUN, TUE, THU), time(9), time(13), 20, "INT-1"),),
    ),
    Doctor(
        "dr.suliman",
        "د. نجلاء سليمان",
        "Dr. Najlaa Suliman",
        "INT",
        "أخصائية الباطنية والسكري",
        "Internal medicine and diabetes",
        "CONS-INT",
        (
            Session((SAT, MON, WED), time(9), time(13), 20, "INT-2"),
            Session((SAT, MON, WED), time(17), time(20), 20, "INT-2"),
        ),
    ),
    Doctor(
        "dr.alzain",
        "د. فاطمة الزين",
        "Dr. Fatima Alzain",
        "PED",
        "استشارية طب الأطفال",
        "Consultant pediatrician",
        "CONS-PED",
        (Session(_WEEK, time(8), time(13), 15, "PED-1"),),
    ),
    Doctor(
        "dr.fadul",
        "د. ياسر فضل",
        "Dr. Yasir Fadul",
        "PED",
        "طب الأطفال",
        "Pediatrics",
        "CONS-PED",
        (Session((SUN, MON, TUE, WED, THU), time(15), time(20), 15, "PED-2"),),
    ),
    Doctor(
        "dr.awad",
        "د. سلمى عوض",
        "Dr. Salma Awad",
        "GYN",
        "استشارية النساء والتوليد",
        "Consultant obstetrician",
        "CONS-GYN",
        (Session((SAT, MON, WED), time(10), time(14), 20, "GYN-1"),),
    ),
    Doctor(
        "dr.gasim",
        "د. هبة قاسم",
        "Dr. Hiba Gasim",
        "GYN",
        "النساء والتوليد",
        "Obstetrics and gynecology",
        "CONS-GYN",
        (Session((SUN, TUE, THU), time(16), time(20), 20, "GYN-2"),),
    ),
    Doctor(
        "dr.idris",
        "د. مازن إدريس",
        "Dr. Mazin Idris",
        "DEN",
        "طب الأسنان",
        "Dentistry",
        "CONS-DEN",
        (Session((SUN, MON, TUE, WED, THU), time(16), time(20), 30, "DEN-1"),),
    ),
    Doctor(
        "dr.osman",
        "د. رشا عثمان",
        "Dr. Rasha Osman",
        "DEN",
        "طب الأسنان",
        "Dentistry",
        "CONS-DEN",
        (Session((SAT, SUN, MON, TUE, WED), time(9), time(13), 30, "DEN-2"),),
    ),
)


@dataclass(frozen=True, slots=True)
class StaffUser:
    username: str
    role: str
    full_name_ar: str
    full_name_en: str


#: One account per role, a second cashier for the evening shift (role codes of core.roles).
STAFF: tuple[StaffUser, ...] = (
    StaffUser("reception", "receptionist", "سارة عبدالله", "Sara Abdalla"),
    StaffUser("cashier", "cashier", "محمد عثمان", "Mohamed Osman"),
    StaffUser("cashier2", "cashier", "إيمان الطيب", "Iman Altayeb"),
    StaffUser("cashsup", "cashier_supervisor", "هالة إبراهيم", "Hala Ibrahim"),
    StaffUser("pharmacist", "pharmacist", "عمر الفاتح", "Omer Alfatih"),
    StaffUser("labtech", "lab_tech", "منى حسن", "Muna Hassan"),
    StaffUser("labsup", "lab_supervisor", "بكري الحسن", "Bakri Alhassan"),
    StaffUser("nurse", "nurse", "آمنة يوسف", "Amna Yousif"),
    StaffUser("accountant", "accountant", "طارق الأمين", "Tarig Alamin"),
    StaffUser("manager", "manager", "نادية محمود", "Nadia Mahmoud"),
    StaffUser("admin", "admin", "مدير النظام", "System Admin"),
)

# --- services ----------------------------------------------------------------------------------

CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("CONS", "الكشوفات", "Consultations"),
    ("HEM", "أمراض الدم", "Hematology"),
    ("CHEM", "الكيمياء الحيوية", "Clinical chemistry"),
    ("HORM", "الهرمونات", "Hormones"),
    ("MICRO", "الأحياء الدقيقة والطفيليات", "Microbiology and parasitology"),
    ("SERO", "الأمصال والمناعة", "Serology and immunology"),
    ("PROC", "الإجراءات", "Procedures"),
    ("OBS", "إجراءات النساء", "Obstetric procedures"),
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
    price: int


CONSULTATIONS: tuple[ServiceDef, ...] = (
    ServiceDef(
        "CONS-GEN", "consultation", "GEN", "CONS", "كشف طب عام", "General consultation", 15000
    ),
    ServiceDef(
        "CONS-INT",
        "consultation",
        "INT",
        "CONS",
        "كشف باطنية",
        "Internal medicine consultation",
        25000,
    ),
    ServiceDef(
        "CONS-PED", "consultation", "PED", "CONS", "كشف أطفال", "Pediatric consultation", 20000
    ),
    ServiceDef(
        "CONS-GYN",
        "consultation",
        "GYN",
        "CONS",
        "كشف نساء وتوليد",
        "Gynecology consultation",
        25000,
    ),
    ServiceDef(
        "CONS-DEN", "consultation", "DEN", "CONS", "كشف أسنان", "Dental consultation", 15000
    ),
)

PROCEDURES: tuple[ServiceDef, ...] = (
    ServiceDef(
        "PRC-INJ", "procedure", "PRC", "PROC", "حقنة عضلية", "Intramuscular injection", 2000
    ),
    ServiceDef(
        "PRC-IVINJ", "procedure", "PRC", "PROC", "حقنة وريدية", "Intravenous injection", 3000
    ),
    ServiceDef(
        "PRC-CANNULA", "procedure", "PRC", "PROC", "تركيب كانيولا", "IV cannula insertion", 3000
    ),
    ServiceDef("PRC-DRIP", "procedure", "PRC", "PROC", "تركيب محلول وريدي", "IV infusion", 6000),
    ServiceDef("PRC-DRESS", "procedure", "PRC", "PROC", "غيار جرح", "Wound dressing", 5000),
    ServiceDef("PRC-SUTURE", "procedure", "PRC", "PROC", "خياطة جرح", "Wound suturing", 15000),
    ServiceDef(
        "PRC-NEB", "procedure", "PRC", "PROC", "جلسة بخار (نيبولايزر)", "Nebulizer session", 4000
    ),
    ServiceDef(
        "PRC-ECG", "procedure", "PRC", "PROC", "تخطيط القلب", "Electrocardiogram (ECG)", 10000
    ),
    ServiceDef(
        "PRC-CATH", "procedure", "PRC", "PROC", "تركيب قسطرة بولية", "Urinary catheter", 8000
    ),
    ServiceDef("PRC-EARWASH", "procedure", "PRC", "PROC", "غسيل أذن", "Ear irrigation", 6000),
    ServiceDef(
        "PRC-GLUCO", "procedure", "PRC", "PROC", "قياس سكر سريع", "Capillary glucose check", 1500
    ),
    ServiceDef(
        "GYN-US", "procedure", "GYN", "OBS", "موجات صوتية للحمل", "Obstetric ultrasound", 20000
    ),
    ServiceDef(
        "GYN-PELVUS", "procedure", "GYN", "OBS", "موجات صوتية للحوض", "Pelvic ultrasound", 20000
    ),
    ServiceDef(
        "GYN-CTG", "procedure", "GYN", "OBS", "تخطيط قلب الجنين", "Cardiotocography (CTG)", 12000
    ),
    ServiceDef("DEN-EXT", "procedure", "DEN", "DENT", "خلع سن", "Tooth extraction", 25000),
    ServiceDef("DEN-FILL", "procedure", "DEN", "DENT", "حشوة سن", "Tooth filling", 30000),
    ServiceDef(
        "DEN-SCALE", "procedure", "DEN", "DENT", "تنظيف الجير", "Scaling and polishing", 20000
    ),
    ServiceDef("DEN-RCT", "procedure", "DEN", "DENT", "علاج عصب", "Root canal treatment", 80000),
    ServiceDef("DEN-XRAY", "procedure", "DEN", "DENT", "أشعة سن", "Dental X-ray", 8000),
)

BED_SERVICES: tuple[ServiceDef, ...] = (
    ServiceDef("BED-WARD", "bed", "WRD", "BED", "إقامة يومية - عنبر", "Ward bed day", 30000),
    ServiceDef(
        "BED-PRIV", "bed", "WRD", "BED", "إقامة يومية - غرفة خاصة", "Private room bed day", 60000
    ),
)

#: Consultation prices from the mid-month price review (FEATURES 5.2, invariant 6).
PRICE_REVIEW: dict[str, int] = {
    "CONS-GEN": 17000,
    "CONS-INT": 28000,
    "CONS-PED": 22000,
    "CONS-GYN": 28000,
    "CONS-DEN": 17000,
    "PRC-ECG": 12000,
    "GYN-US": 22000,
}

# --- payers ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rule:
    rule_kind: str
    service: str | None = None
    service_kind: str | None = None
    payer_percent: int | None = None
    copay: int | None = None
    ceiling: int | None = None
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
    #: Contract price = cash price x factor (percent).
    price_percent: int
    requires_card_number: bool
    claim_period: str
    contract_no: str
    phone: str
    rules: tuple[Rule, ...]
    exclusions: tuple[str, ...] = ()
    #: Share of new patients who carry this payer's card.
    share: float = 0.0


PAYERS: tuple[PayerDef, ...] = (
    PayerDef(
        "WAHA",
        "insurance",
        "الواحة للتأمين الصحي التكافلي (تجريبية)",
        "Al-Waha Takaful Health Insurance (demo)",
        "أسعار الواحة للتأمين",
        "Al-Waha insurance prices",
        90,
        True,
        "monthly",
        "WAH-2026-017",
        "+249 912 300 101",
        (
            Rule("percentage", payer_percent=75, note="75% of every line"),
            Rule("percentage", service_kind="drug", payer_percent=60, note="Medicines at 60%"),
            Rule(
                "percentage",
                service="GYN-US",
                payer_percent=75,
                pre_approval=True,
                note="Pre-approval reference required",
            ),
        ),
        exclusions=("DEN-FILL", "DEN-RCT", "DEN-SCALE"),
        share=0.18,
    ),
    PayerDef(
        "SALAM",
        "company",
        "مجموعة السلام للصناعات الغذائية (تجريبية)",
        "Assalam Food Industries Group (demo)",
        "أسعار مجموعة السلام",
        "Assalam Group prices",
        100,
        True,
        "monthly",
        "SLM-2026-004",
        "+249 912 300 102",
        (Rule("copay", copay=3000, note="Employee pays 3,000 per line"),),
        share=0.10,
    ),
    PayerDef(
        "AMAL",
        "ngo",
        "منظمة الأمل الخيرية (تجريبية)",
        "Al-Amal Charity (demo)",
        "أسعار منظمة الأمل",
        "Al-Amal Charity prices",
        85,
        False,
        "quarterly",
        "AML-2026-009",
        "+249 912 300 103",
        (Rule("ceiling", payer_percent=100, ceiling=15000, note="Up to 15,000 per line"),),
        share=0.07,
    ),
)

# --- pharmacy ----------------------------------------------------------------------------------

DRUG_CLASSES: tuple[tuple[str, str, str], ...] = (
    ("PENICILLIN", "البنسلينات", "Penicillins"),
    ("CEPHALOSPORIN", "السيفالوسبورينات", "Cephalosporins"),
    ("NSAID", "مضادات الالتهاب غير الستيرويدية", "NSAIDs"),
    ("SULFONAMIDE", "السلفوناميدات", "Sulfonamides"),
    ("MACROLIDE", "الماكروليدات", "Macrolides"),
    ("QUINOLONE", "الكينولونات", "Quinolones"),
)

#: Base units: code -> (name_ar, name_en, dosage form default, breaks into strips of 10).
UNITS: dict[str, tuple[str, str]] = {
    "tablet": ("قرص", "Tablet"),
    "capsule": ("كبسولة", "Capsule"),
    "bottle": ("زجاجة", "Bottle"),
    "vial": ("قارورة", "Vial"),
    "ampoule": ("أمبولة", "Ampoule"),
    "tube": ("أنبوب", "Tube"),
    "sachet": ("كيس", "Sachet"),
    "inhaler": ("بخاخ", "Inhaler"),
    "bag": ("كيس محلول", "Infusion bag"),
    "pessary": ("تحميلة مهبلية", "Pessary"),
    "suppository": ("تحميلة", "Suppository"),
    "piece": ("قطعة", "Piece"),
    "pack": ("عبوة", "Pack"),
    "pair": ("زوج", "Pair"),
    "roll": ("لفة", "Roll"),
    "cartridge": ("خرطوشة", "Cartridge"),
}

#: unit code -> dosage form.
FORM_OF_UNIT: dict[str, str] = {
    "tablet": "tablet",
    "capsule": "capsule",
    "bottle": "syrup",
    "vial": "injection",
    "ampoule": "injection",
    "tube": "cream",
    "sachet": "sachet",
    "inhaler": "inhaler",
    "bag": "infusion",
    "pessary": "suppository",
    "suppository": "suppository",
    "cartridge": "injection",
}


@dataclass(frozen=True, slots=True)
class DrugDef:
    code: str
    generic: str
    name_ar: str
    strength: str
    unit: str
    pack: int
    price: int
    classes: tuple[str, ...]
    #: 1 (rarely used) .. 5 (used every day): drives stock levels.
    popularity: int
    storage: str = "room"
    form: str = ""

    @property
    def service_code(self) -> str:
        return f"DRG-{self.code}"


# code | generic (English) | Arabic name | strength | base unit | pack | price | classes | pop
# (storage "fridge" marked with a trailing *).
_DRUG_TABLE = """
PARA500|Paracetamol|باراسيتامول|500 mg|tablet|100|50||5
PARASYR|Paracetamol syrup|باراسيتامول شراب|120 mg/5 ml, 60 ml|bottle|12|1500||4
PARASUP|Paracetamol suppository|باراسيتامول تحاميل|125 mg|suppository|10|300||2
PARAINF|Paracetamol infusion|باراسيتامول محلول وريدي|1 g/100 ml|bag|12|4000||2
IBU400|Ibuprofen|إيبوبروفين|400 mg|tablet|30|100|NSAID|4
IBU200|Ibuprofen|إيبوبروفين|200 mg|tablet|30|60|NSAID|2
IBUSYR|Ibuprofen suspension|إيبوبروفين شراب|100 mg/5 ml, 100 ml|bottle|12|2000|NSAID|3
DICLO50|Diclofenac sodium|ديكلوفيناك صوديوم|50 mg|tablet|20|80|NSAID|3
DICLOINJ|Diclofenac sodium injection|ديكلوفيناك حقن|75 mg/3 ml|ampoule|10|600|NSAID|3
DICLOGEL|Diclofenac gel|ديكلوفيناك جل|1%, 50 g|tube|10|2500|NSAID|2
MEFEN500|Mefenamic acid|حمض الميفيناميك|500 mg|tablet|20|120|NSAID|2
NAPROX500|Naproxen|نابروكسين|500 mg|tablet|20|150|NSAID|1
ASA81|Acetylsalicylic acid|أسبرين|81 mg|tablet|30|40|NSAID|3
TRAMA50|Tramadol|ترامادول|50 mg|capsule|20|200||1
KETOINJ|Ketorolac injection|كيتورولاك حقن|30 mg/ml|ampoule|10|1200|NSAID|1
METAM500|Metamizole sodium|ميتاميزول صوديوم|500 mg|tablet|20|80||3
METAMINJ|Metamizole injection|ميتاميزول حقن|1 g/2 ml|ampoule|10|800||3
AMOX250|Amoxicillin|أموكسيسيلين|250 mg|capsule|20|200|PENICILLIN|2
AMOX500|Amoxicillin|أموكسيسيلين|500 mg|capsule|20|300|PENICILLIN|5
AMOXSYR|Amoxicillin suspension|أموكسيسيلين شراب|125 mg/5 ml, 100 ml|bottle|12|2500|PENICILLIN|4
AMOXSYR250|Amoxicillin suspension|أموكسيسيلين شراب|250 mg/5 ml, 100 ml|bottle|12|3000|PENICILLIN|2
COAMOX625|Amoxicillin/clavulanate|أموكسيسيلين وكلافيولانات|625 mg|tablet|14|900|PENICILLIN|4
COAMOX1G|Amoxicillin/clavulanate|أموكسيسيلين وكلافيولانات|1 g|tablet|14|1300|PENICILLIN|2
COAMOXSYR|Amoxicillin/clavulanate suspension|أموكسيسيلين وكلافيولانات شراب|228 mg/5 ml, 70 ml|bottle|10|6000|PENICILLIN|2
AMPIINJ|Ampicillin injection|أمبيسيلين حقن|500 mg|vial|10|1500|PENICILLIN|1
PENV250|Phenoxymethylpenicillin|فينوكسي ميثيل بنسلين|250 mg|tablet|20|100|PENICILLIN|1
BENZAPEN|Benzathine benzylpenicillin|بنزاثين بنسلين|2.4 MU|vial|10|3000|PENICILLIN|1
CLOXA500|Cloxacillin|كلوكساسيلين|500 mg|capsule|20|250|PENICILLIN|1
FLUCLOX500|Flucloxacillin|فلوكلوكساسيلين|500 mg|capsule|20|400|PENICILLIN|2
CEPHA500|Cefalexin|سيفالكسين|500 mg|capsule|20|400|CEPHALOSPORIN|2
CEPHASYR|Cefalexin suspension|سيفالكسين شراب|250 mg/5 ml, 100 ml|bottle|12|3500|CEPHALOSPORIN|2
CEFUR500|Cefuroxime|سيفوروكسيم|500 mg|tablet|10|1200|CEPHALOSPORIN|2
CEFIX400|Cefixime|سيفيكسيم|400 mg|capsule|5|1500|CEPHALOSPORIN|3
CEFIXSYR|Cefixime suspension|سيفيكسيم شراب|100 mg/5 ml, 60 ml|bottle|10|5000|CEPHALOSPORIN|2
CEFTRI1G|Ceftriaxone injection|سيفترياكسون حقن|1 g|vial|10|3500|CEPHALOSPORIN|4
CEFTRI500|Ceftriaxone injection|سيفترياكسون حقن|500 mg|vial|10|2500|CEPHALOSPORIN|2
CEFOTAX1G|Cefotaxime injection|سيفوتاكسيم حقن|1 g|vial|10|3000|CEPHALOSPORIN|1
AZI250|Azithromycin|أزيثرومايسين|250 mg|capsule|6|800|MACROLIDE|2
AZI500|Azithromycin|أزيثرومايسين|500 mg|tablet|3|1400|MACROLIDE|4
AZISYR|Azithromycin suspension|أزيثرومايسين شراب|200 mg/5 ml, 15 ml|bottle|10|5000|MACROLIDE|3
CLARI500|Clarithromycin|كلاريثرومايسين|500 mg|tablet|14|1500|MACROLIDE|2
ERY250|Erythromycin|إريثرومايسين|250 mg|tablet|20|250|MACROLIDE|1
CIPRO500|Ciprofloxacin|سيبروفلوكساسين|500 mg|tablet|10|300|QUINOLONE|4
CIPRO250|Ciprofloxacin|سيبروفلوكساسين|250 mg|tablet|10|200|QUINOLONE|1
CIPROINF|Ciprofloxacin infusion|سيبروفلوكساسين محلول وريدي|200 mg/100 ml|bag|10|3000|QUINOLONE|1
LEVO500|Levofloxacin|ليفوفلوكساسين|500 mg|tablet|7|900|QUINOLONE|2
METRO500|Metronidazole|ميترونيدازول|500 mg|tablet|20|150||5
METRO250|Metronidazole|ميترونيدازول|250 mg|tablet|20|100||2
METROSYR|Metronidazole suspension|ميترونيدازول شراب|200 mg/5 ml, 100 ml|bottle|12|2000||3
METROINF|Metronidazole infusion|ميترونيدازول محلول وريدي|500 mg/100 ml|bag|10|2500||2
DOXY100|Doxycycline|دوكسيسايكلين|100 mg|capsule|10|150||3
COTRI480|Co-trimoxazole|كوتريموكسازول|480 mg|tablet|20|80|SULFONAMIDE|2
COTRI960|Co-trimoxazole|كوتريموكسازول|960 mg|tablet|10|140|SULFONAMIDE|2
COTRISYR|Co-trimoxazole suspension|كوتريموكسازول شراب|240 mg/5 ml, 100 ml|bottle|12|2000|SULFONAMIDE|2
NITRO100|Nitrofurantoin|نيتروفورانتوين|100 mg|capsule|20|250||2
GENTAINJ|Gentamicin injection|جنتاميسين حقن|80 mg/2 ml|ampoule|10|700||2
CLINDA300|Clindamycin|كليندامايسين|300 mg|capsule|16|700||1
TINID500|Tinidazole|تينيدازول|500 mg|tablet|4|300||2
COART|Artemether/lumefantrine|أرتيميثر ولوميفانترين|20/120 mg|tablet|24|500||5
COARTDISP|Artemether/lumefantrine dispersible|أرتيميثر ولوميفانترين للأطفال|20/120 mg|tablet|12|450||3
COART80|Artemether/lumefantrine|أرتيميثر ولوميفانترين|80/480 mg|tablet|6|1500||3
ARTEMINJ|Artemether injection|أرتيميثر حقن|80 mg/ml|ampoule|6|1800||3
ARTESUN60|Artesunate injection|أرتيسونات حقن|60 mg|vial|10|3500||3
QUIN300|Quinine sulfate|كينين|300 mg|tablet|20|200||1
QUININJ|Quinine injection|كينين حقن|600 mg/2 ml|ampoule|10|900||1
PRIMA15|Primaquine|بريماكين|15 mg|tablet|14|300||1
DHAPQ|Dihydroartemisinin/piperaquine|داي هيدرو أرتيميسينين وبيبراكين|40/320 mg|tablet|9|1200||2
FLUCO150|Fluconazole|فلوكونازول|150 mg|capsule|1|600||2
FLUCO50|Fluconazole|فلوكونازول|50 mg|capsule|7|300||1
CLOTRICR|Clotrimazole cream|كلوتريمازول كريم|1%, 20 g|tube|10|1500||2
CLOTRIVAG|Clotrimazole vaginal tablet|كلوتريمازول أقراص مهبلية|500 mg|pessary|1|1500||2
MICONGEL|Miconazole oral gel|ميكونازول جل فموي|2%, 15 g|tube|10|3000||1
NYSTSUSP|Nystatin suspension|نيستاتين معلق|100,000 IU/ml, 30 ml|bottle|10|3000||1
TERBICR|Terbinafine cream|تيربينافين كريم|1%, 15 g|tube|10|3500||1
ALBEN400|Albendazole|ألبيندازول|400 mg|tablet|1|300||3
ALBENSYR|Albendazole suspension|ألبيندازول شراب|200 mg/5 ml, 10 ml|bottle|12|1500||2
MEBEN100|Mebendazole|ميبيندازول|100 mg|tablet|6|100||2
PRAZI600|Praziquantel|برازيكوانتيل|600 mg|tablet|4|700||2
IVERM6|Ivermectin|إيفرمكتين|6 mg|tablet|4|500||1
DILOX500|Diloxanide furoate|ديلوكسانيد|500 mg|tablet|30|300||1
OMEP20|Omeprazole|أوميبرازول|20 mg|capsule|14|150||5
OMEPINJ|Omeprazole injection|أوميبرازول حقن|40 mg|vial|10|3000||2
ESOME40|Esomeprazole|إيزوميبرازول|40 mg|tablet|14|400||2
PANTO40|Pantoprazole|بانتوبرازول|40 mg|tablet|14|350||2
FAMO40|Famotidine|فاموتيدين|40 mg|tablet|20|150||1
ANTACID|Aluminium/magnesium hydroxide suspension|مضاد حموضة شراب|200 ml|bottle|12|1800||3
METOC10|Metoclopramide|ميتوكلوبراميد|10 mg|tablet|20|60||2
METOCINJ|Metoclopramide injection|ميتوكلوبراميد حقن|10 mg/2 ml|ampoule|10|400||3
DOMPER10|Domperidone|دومبيريدون|10 mg|tablet|30|100||2
ONDAN4|Ondansetron|أوندانسيترون|4 mg|tablet|10|300||2
ONDANINJ|Ondansetron injection|أوندانسيترون حقن|4 mg/2 ml|ampoule|5|1000||2
HYOSC10|Hyoscine butylbromide|هيوسين بيوتيل بروميد|10 mg|tablet|20|100||3
HYOSCINJ|Hyoscine butylbromide injection|هيوسين حقن|20 mg/ml|ampoule|10|700||3
ORS|Oral rehydration salts|أملاح الإرواء الفموي|20.5 g|sachet|50|300||5
ZINC20|Zinc sulfate dispersible|زنك أقراص ذائبة|20 mg|tablet|10|80||3
LOPER2|Loperamide|لوبيراميد|2 mg|capsule|10|80||1
BISAC5|Bisacodyl|بيساكوديل|5 mg|tablet|20|50||1
LACTUL|Lactulose syrup|لاكتيولوز شراب|200 ml|bottle|10|4000||1
MEBEV135|Mebeverine|ميبيفيرين|135 mg|tablet|30|200||2
SIMETH|Simethicone drops|سيميثيكون نقط|40 mg/ml, 30 ml|bottle|10|2500||2
AMLO5|Amlodipine|أملوديبين|5 mg|tablet|30|80||4
AMLO10|Amlodipine|أملوديبين|10 mg|tablet|30|120||2
NIFE20|Nifedipine retard|نيفيديبين ممتد المفعول|20 mg|tablet|30|100||2
ATEN50|Atenolol|أتينولول|50 mg|tablet|28|60||2
BISO5|Bisoprolol|بيسوبرولول|5 mg|tablet|30|150||2
CARVE625|Carvedilol|كارفيديلول|6.25 mg|tablet|30|150||1
ENAL10|Enalapril|إنالابريل|10 mg|tablet|20|70||3
LISIN10|Lisinopril|ليسينوبريل|10 mg|tablet|28|100||2
CAPTO25|Captopril|كابتوبريل|25 mg|tablet|20|50||1
LOSAR50|Losartan|لوسارتان|50 mg|tablet|30|150||3
VALS80|Valsartan|فالسارتان|80 mg|tablet|28|250||2
HCTZ25|Hydrochlorothiazide|هيدروكلوروثيازيد|25 mg|tablet|30|40||2
FURO40|Furosemide|فوروسيميد|40 mg|tablet|20|40||2
FUROINJ|Furosemide injection|فوروسيميد حقن|20 mg/2 ml|ampoule|10|300||2
SPIRO25|Spironolactone|سبيرونولاكتون|25 mg|tablet|20|150||1
ATOR20|Atorvastatin|أتورفاستاتين|20 mg|tablet|30|200||3
ATOR40|Atorvastatin|أتورفاستاتين|40 mg|tablet|30|300||2
SIMVA20|Simvastatin|سيمفاستاتين|20 mg|tablet|28|120||1
ROSU10|Rosuvastatin|روزوفاستاتين|10 mg|tablet|28|300||2
CLOPI75|Clopidogrel|كلوبيدوقريل|75 mg|tablet|28|250||2
WARF5|Warfarin|وارفارين|5 mg|tablet|28|100||1
DIGOX025|Digoxin|ديجوكسين|0.25 mg|tablet|30|80||1
ISMN20|Isosorbide mononitrate|إيزوسوربيد أحادي النترات|20 mg|tablet|30|100||1
MDOPA250|Methyldopa|ميثيل دوبا|250 mg|tablet|30|80||2
HYDRALINJ|Hydralazine injection|هيدرالازين حقن|20 mg|ampoule|5|2500||1
METF500|Metformin|ميتفورمين|500 mg|tablet|30|50||4
METF850|Metformin|ميتفورمين|850 mg|tablet|30|70||3
METF1000|Metformin|ميتفورمين|1000 mg|tablet|30|90||2
GLIB5|Glibenclamide|جليبنكلاميد|5 mg|tablet|30|40||2
GLICL80|Gliclazide|جليكلازايد|80 mg|tablet|30|80||2
GLICLMR30|Gliclazide modified release|جليكلازايد ممتد المفعول|30 mg|tablet|30|120||2
GLIM2|Glimepiride|جليميبرايد|2 mg|tablet|30|100||2
SITA50|Sitagliptin|سيتاجلبتين|50 mg|tablet|28|600||1
INSNPH|Insulin isophane (NPH)|إنسولين متوسط المفعول|100 IU/ml, 10 ml|vial|1|9000||2|*
INSREG|Insulin regular|إنسولين سريع المفعول|100 IU/ml, 10 ml|vial|1|9000||2|*
INSMIX|Insulin 70/30|إنسولين مخلوط 70/30|100 IU/ml, 10 ml|vial|1|9500||2|*
SALBINH|Salbutamol inhaler|سالبيوتامول بخاخ|100 mcg/dose|inhaler|1|4000||3
SALBNEB|Salbutamol nebules|سالبيوتامول محلول تبخير|2.5 mg/2.5 ml|ampoule|20|300||3
SALBSYR|Salbutamol syrup|سالبيوتامول شراب|2 mg/5 ml, 100 ml|bottle|12|1500||2
SALB4|Salbutamol|سالبيوتامول|4 mg|tablet|30|40||1
BUDINH|Budesonide inhaler|بوديسونايد بخاخ|200 mcg/dose|inhaler|1|9000||1
BECLOINH|Beclometasone inhaler|بيكلوميثازون بخاخ|100 mcg/dose|inhaler|1|7000||1
IPRANEB|Ipratropium nebules|إبراتروبيوم محلول تبخير|250 mcg/ml|ampoule|20|600||2
AMINO100|Aminophylline|أمينوفيلين|100 mg|tablet|30|50||1
MONTE10|Montelukast|مونتيلوكاست|10 mg|tablet|28|300||2
CETI10|Cetirizine|سيتريزين|10 mg|tablet|20|60||4
CETISYR|Cetirizine syrup|سيتريزين شراب|5 mg/5 ml, 60 ml|bottle|12|1500||3
LORA10|Loratadine|لوراتادين|10 mg|tablet|20|70||2
CPM4|Chlorphenamine|كلورفينامين|4 mg|tablet|30|30||2
CPMINJ|Chlorphenamine injection|كلورفينامين حقن|10 mg/ml|ampoule|10|400||2
PROMETH25|Promethazine|بروميثازين|25 mg|tablet|20|60||1
DXMSYR|Dextromethorphan syrup|ديكستروميثورفان شراب|15 mg/5 ml, 100 ml|bottle|12|1800||3
AMBROSYR|Ambroxol syrup|أمبروكسول شراب|15 mg/5 ml, 100 ml|bottle|12|1800||3
CARBOSYR|Carbocisteine syrup|كاربوسيستين شراب|250 mg/5 ml, 100 ml|bottle|12|2000||2
PRED5|Prednisolone|بريدنيزولون|5 mg|tablet|30|30||3
PREDSYR|Prednisolone syrup|بريدنيزولون شراب|15 mg/5 ml, 60 ml|bottle|10|2500||2
DEXAINJ|Dexamethasone injection|ديكساميثازون حقن|4 mg/ml|ampoule|10|300||3
HCORTINJ|Hydrocortisone injection|هيدروكورتيزون حقن|100 mg|vial|10|1500||2
XYLODROP|Xylometazoline nasal drops|زايلوميتازولين نقط أنف|0.1%, 10 ml|bottle|10|1500||2
SALINDROP|Saline nasal drops|نقط أنف ملحية|0.9%, 15 ml|bottle|10|800||2
FEFOL|Ferrous sulfate/folic acid|كبريتات الحديدوز وحمض الفوليك|200 mg/0.4 mg|tablet|30|50||4
FESYR|Iron syrup|حديد شراب|50 mg/5 ml, 100 ml|bottle|12|2500||2
FOLIC5|Folic acid|حمض الفوليك|5 mg|tablet|30|20||3
VITBCO|Vitamin B complex|فيتامين ب المركب|tablet|tablet|30|30||2
VITC500|Ascorbic acid|فيتامين ج|500 mg|tablet|30|40||2
CALCD3|Calcium carbonate/vitamin D3|كالسيوم وفيتامين د3|600 mg/400 IU|tablet|30|120||2
VITD50K|Colecalciferol|فيتامين د3|50,000 IU|capsule|4|600||2
MULTISYR|Multivitamin syrup|فيتامينات متعددة شراب|100 ml|bottle|12|2500||2
B12INJ|Cyanocobalamin injection|فيتامين ب12 حقن|1 mg/ml|ampoule|10|500||2
OXYTINJ|Oxytocin injection|أوكسيتوسين حقن|10 IU/ml|ampoule|10|700||1|*
MISO200|Misoprostol|ميزوبروستول|200 mcg|tablet|4|800||1
MGSO4|Magnesium sulfate injection|كبريتات المغنيسيوم حقن|50%, 10 ml|ampoule|10|1500||1
DYDRO10|Dydrogesterone|ديدروجستيرون|10 mg|tablet|20|900||2
NORETH5|Norethisterone|نوريثيستيرون|5 mg|tablet|30|150||2
CLOMI50|Clomifene citrate|كلوميفين|50 mg|tablet|10|600||1
COC|Levonorgestrel/ethinylestradiol|حبوب منع الحمل المركبة|0.15/0.03 mg|tablet|21|100||1
METROVAG|Metronidazole vaginal tablet|ميترونيدازول أقراص مهبلية|500 mg|pessary|10|800||2
HCORTCR|Hydrocortisone cream|هيدروكورتيزون كريم|1%, 15 g|tube|10|1500||2
BETAMCR|Betamethasone cream|بيتاميثازون كريم|0.1%, 15 g|tube|10|2000||2
FUSIDCR|Fusidic acid cream|حمض الفيوسيديك كريم|2%, 15 g|tube|10|3500||2
MUPIROINT|Mupirocin ointment|موبيروسين مرهم|2%, 15 g|tube|10|4000||1
CALAMINE|Calamine lotion|غسول الكالامين|100 ml|bottle|12|1500||1
PERMCR|Permethrin cream|بيرميثرين كريم|5%, 30 g|tube|10|3000||1
SSDCR|Silver sulfadiazine cream|سلفاديازين الفضة كريم|1%, 50 g|tube|10|4000|SULFONAMIDE|1
CHLOREYE|Chloramphenicol eye drops|كلورامفينيكول قطرة عين|0.5%, 10 ml|bottle|10|1500||2
TOBRAEYE|Tobramycin eye drops|توبرامايسين قطرة عين|0.3%, 5 ml|bottle|10|3000||1
TETRAEYE|Tetracycline eye ointment|تتراسايكلين مرهم عين|1%, 5 g|tube|10|1000||2
CIPROEAR|Ciprofloxacin ear drops|سيبروفلوكساسين قطرة أذن|0.3%, 10 ml|bottle|10|2000|QUINOLONE|2
ARTTEARS|Artificial tears|دموع صناعية|10 ml|bottle|10|2500||1
GENTEYE|Gentamicin eye drops|جنتاميسين قطرة عين|0.3%, 10 ml|bottle|10|1200||1
DIAZ5|Diazepam|ديازيبام|5 mg|tablet|20|50||1
DIAZINJ|Diazepam injection|ديازيبام حقن|10 mg/2 ml|ampoule|10|500||1
PHENOB30|Phenobarbital|فينوباربيتال|30 mg|tablet|30|40||1
CARBA200|Carbamazepine|كاربامازيبين|200 mg|tablet|30|80||1
VALPRO500|Sodium valproate|فالبروات الصوديوم|500 mg|tablet|30|250||1
PHENY100|Phenytoin|فينيتوين|100 mg|capsule|30|70||1
AMITRIP25|Amitriptyline|أميتريبتيلين|25 mg|tablet|30|40||1
FLUOX20|Fluoxetine|فلوكسيتين|20 mg|capsule|28|120||1
HALOP5|Haloperidol|هالوبيريدول|5 mg|tablet|30|60||1
OLANZ10|Olanzapine|أولانزابين|10 mg|tablet|28|300||1
GABA300|Gabapentin|جابابنتين|300 mg|capsule|30|250||1
PREGAB75|Pregabalin|بريجابالين|75 mg|capsule|28|300||2
BETAH16|Betahistine|بيتاهيستين|16 mg|tablet|30|120||2
CINNA25|Cinnarizine|سيناريزين|25 mg|tablet|30|60||2
TAMSU04|Tamsulosin|تامسولوسين|0.4 mg|capsule|30|300||1
POTCIT|Potassium citrate|سترات البوتاسيوم|3 g|sachet|20|600||1
NS500|Sodium chloride infusion|محلول ملح 0.9%|0.9%, 500 ml|bag|20|1500||3
DEX5|Dextrose infusion|محلول جلوكوز 5%|5%, 500 ml|bag|20|1500||2
RL500|Ringer's lactate infusion|محلول رينجر لاكتات|500 ml|bag|20|1700||3
DNS500|Dextrose/saline infusion|محلول جلوكوز وملح|5%/0.9%, 500 ml|bag|20|1600||2
WFI10|Water for injection|ماء للحقن|10 ml|ampoule|50|150||3
DEX50|Dextrose 50% injection|جلوكوز 50% حقن|50 ml|vial|10|1200||1
LIDO2|Lidocaine injection|ليدوكايين حقن|2%, 20 ml|vial|10|1500||2
ADRENINJ|Adrenaline injection|أدرينالين حقن|1 mg/ml|ampoule|10|800||1
ATROPINJ|Atropine injection|أتروبين حقن|1 mg/ml|ampoule|10|500||1
TETANUS|Tetanus toxoid vaccine|لقاح التيتانوس|0.5 ml|ampoule|10|1500||2|*
CHXMW|Chlorhexidine mouthwash|غسول فم كلورهيكسيدين|0.12%, 250 ml|bottle|12|2500||2
BENZOGEL|Benzocaine oral gel|بنزوكايين جل للفم|20%, 10 g|tube|10|2000||1
LIDODENT|Lidocaine/adrenaline dental cartridge|ليدوكايين مع أدرينالين للأسنان|2%, 1.8 ml|cartridge|50|700||2
"""

# code | name (English) | Arabic | detail | base unit | pack | price | pop
_SUPPLY_TABLE = """
SYR2|Syringe 2 ml|حقنة 2 مل|2 ml|piece|100|150|4
SYR5|Syringe 5 ml|حقنة 5 مل|5 ml|piece|100|200|4
SYR10|Syringe 10 ml|حقنة 10 مل|10 ml|piece|100|250|3
CANNULA20|IV cannula 20G|كانيولا 20G|20G|piece|50|1500|3
CANNULA22|IV cannula 22G|كانيولا 22G|22G|piece|50|1500|2
IVSET|IV giving set|جهاز تركيب محلول|adult|piece|50|1200|3
GAUZE|Sterile gauze|شاش معقم|10 x 10 cm|pack|50|500|3
COTTON|Cotton wool|قطن طبي|100 g|roll|20|1200|2
BANDAGE|Crepe bandage|رباط ضاغط|10 cm|roll|20|1500|2
PLASTER|Adhesive plaster|بلاستر لاصق|2.5 cm x 5 m|roll|24|1000|2
GLOVES|Examination gloves|قفازات فحص|medium|pair|50|300|4
FOLEY16|Urinary catheter 16Fr|قسطرة بولية 16|16Fr|piece|10|2500|1
SUTSILK|Silk suture 2/0|خيط جراحي حرير 2/0|2/0|piece|12|2000|2
MASK|Face mask|كمامة طبية|surgical|piece|50|100|3
"""


def _drugs() -> tuple[DrugDef, ...]:
    out: list[DrugDef] = []
    for raw in _DRUG_TABLE.strip().splitlines():
        cols = raw.split("|")
        code, generic, name_ar, strength, unit, pack, price, classes, pop = cols[:9]
        fridge = len(cols) > 9 and cols[9] == "*"
        out.append(
            DrugDef(
                code=code,
                generic=generic,
                name_ar=name_ar,
                strength=strength,
                unit=unit,
                pack=int(pack),
                price=int(price),
                classes=tuple(c for c in classes.split(",") if c),
                popularity=int(pop),
                storage="fridge" if fridge else "room",
            )
        )
    return tuple(out)


@dataclass(frozen=True, slots=True)
class SupplyDef:
    code: str
    name_en: str
    name_ar: str
    detail: str
    unit: str
    pack: int
    price: int
    popularity: int

    @property
    def service_code(self) -> str:
        return f"CNS-{self.code}"


def _supplies() -> tuple[SupplyDef, ...]:
    out: list[SupplyDef] = []
    for raw in _SUPPLY_TABLE.strip().splitlines():
        code, name_en, name_ar, detail, unit, pack, price, pop = raw.split("|")
        out.append(SupplyDef(code, name_en, name_ar, detail, unit, int(pack), int(price), int(pop)))
    return tuple(out)


DRUGS: tuple[DrugDef, ...] = _drugs()
SUPPLIES: tuple[SupplyDef, ...] = _supplies()

STORES: tuple[tuple[str, str, str | None, str, str, bool], ...] = (
    ("MAIN", "main", None, "المخزن الرئيسي", "Main store", False),
    ("PHA", "pharmacy", "PHA", "الصيدلية", "Pharmacy", True),
)

SUPPLIERS: tuple[tuple[str, str, str], ...] = (
    ("SUP-NILE", "شركة النيل للأدوية (تجريبية)", "Nile Pharmaceuticals (demo)"),
    ("SUP-AMIN", "مستودع الأمين للمستلزمات الطبية (تجريبي)", "Alamin Medical Supplies (demo)"),
)

TILLS: tuple[tuple[str, str, str], ...] = (
    ("T1", "الصندوق 1", "Till 1"),
    ("T2", "الصندوق 2", "Till 2"),
)

# --- laboratory --------------------------------------------------------------------------------

ADULT = 18 * 365


@dataclass(frozen=True, slots=True)
class Range:
    sex: str = "any"
    age_min_days: int = 0
    age_max_days: int | None = None
    low: str | None = None
    high: str | None = None
    critical_low: str | None = None
    critical_high: str | None = None
    normal_text: str = ""


@dataclass(frozen=True, slots=True)
class Param:
    code: str
    name_ar: str
    name_en: str
    unit: str
    value_type: str
    decimals: int
    ranges: tuple[Range, ...]
    choices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LabTestDef:
    code: str
    category: str
    name_ar: str
    name_en: str
    price: int
    sample_type: str
    container: str
    turnaround: int
    params: tuple[Param, ...]
    instructions_ar: str = ""
    instructions_en: str = ""
    popularity: int = 1

    @property
    def service_code(self) -> str:
        return f"LAB-{self.code}"


def num(
    code: str,
    name_ar: str,
    name_en: str,
    unit: str,
    decimals: int,
    low: str | None,
    high: str | None,
    critical_low: str | None = None,
    critical_high: str | None = None,
) -> Param:
    return Param(
        code,
        name_ar,
        name_en,
        unit,
        "numeric",
        decimals,
        (Range(low=low, high=high, critical_low=critical_low, critical_high=critical_high),),
    )


def posneg(code: str, name_ar: str, name_en: str) -> Param:
    return Param(code, name_ar, name_en, "", "pos_neg", 0, (Range(normal_text="negative"),))


def sexed(
    code: str,
    name_ar: str,
    name_en: str,
    unit: str,
    decimals: int,
    male: tuple[str, str],
    female: tuple[str, str],
    child: tuple[str, str] | None = None,
) -> Param:
    ranges: list[Range] = []
    if child is not None:
        ranges.append(Range(age_max_days=ADULT, low=child[0], high=child[1]))
        ranges.append(Range(sex="male", age_min_days=ADULT, low=male[0], high=male[1]))
        ranges.append(Range(sex="female", age_min_days=ADULT, low=female[0], high=female[1]))
    else:
        ranges.append(Range(sex="male", low=male[0], high=male[1]))
        ranges.append(Range(sex="female", low=female[0], high=female[1]))
    return Param(code, name_ar, name_en, unit, "numeric", decimals, tuple(ranges))


_TITRES = ("<1:80", "1:80", "1:160", "1:320")
_GRADES = ("nil", "trace", "1+", "2+", "3+")
_HGB = Param(
    "HGB",
    "الهيموغلوبين",
    "Hemoglobin",
    "g/dL",
    "numeric",
    1,
    (
        Range(
            age_max_days=ADULT, low="11.0", high="14.5", critical_low="7.0", critical_high="20.0"
        ),
        Range(
            sex="male",
            age_min_days=ADULT,
            low="13.0",
            high="17.0",
            critical_low="7.0",
            critical_high="20.0",
        ),
        Range(
            sex="female",
            age_min_days=ADULT,
            low="12.0",
            high="15.5",
            critical_low="7.0",
            critical_high="20.0",
        ),
    ),
)

LAB_TESTS: tuple[LabTestDef, ...] = (
    LabTestDef(
        "CBC",
        "HEM",
        "صورة الدم الكاملة",
        "Complete blood count (CBC)",
        12000,
        "whole_blood",
        "EDTA",
        60,
        (
            num(
                "WBC",
                "كريات الدم البيضاء",
                "White blood cells",
                "10^9/L",
                1,
                "4.0",
                "11.0",
                "2.0",
                "30.0",
            ),
            num("RBC", "كريات الدم الحمراء", "Red blood cells", "10^12/L", 2, "4.20", "5.90"),
            _HGB,
            num("HCT", "الهيماتوكريت", "Hematocrit", "%", 1, "36.0", "50.0"),
            num("MCV", "متوسط حجم الكرية", "Mean cell volume", "fL", 0, "80", "100"),
            num("PLT", "الصفائح الدموية", "Platelets", "10^9/L", 0, "150", "450", "50", "1000"),
        ),
        popularity=5,
    ),
    LabTestDef(
        "HB",
        "HEM",
        "الهيموغلوبين",
        "Hemoglobin",
        3000,
        "whole_blood",
        "EDTA",
        30,
        (_HGB,),
        popularity=3,
    ),
    LabTestDef(
        "ESR",
        "HEM",
        "سرعة الترسيب",
        "Erythrocyte sedimentation rate",
        3000,
        "whole_blood",
        "Citrate",
        60,
        (num("ESR", "سرعة الترسيب", "ESR", "mm/hr", 0, "0", "20"),),
        popularity=2,
    ),
    LabTestDef(
        "RETIC",
        "HEM",
        "الخلايا الشبكية",
        "Reticulocyte count",
        5000,
        "whole_blood",
        "EDTA",
        60,
        (num("RETIC", "الخلايا الشبكية", "Reticulocytes", "%", 1, "0.5", "2.5"),),
    ),
    LabTestDef(
        "BG",
        "HEM",
        "فصيلة الدم",
        "Blood group and Rh",
        3000,
        "whole_blood",
        "EDTA",
        30,
        (
            Param(
                "ABO",
                "فصيلة الدم",
                "Blood group",
                "",
                "choice",
                0,
                (),
                ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"),
            ),
        ),
        popularity=2,
    ),
    LabTestDef(
        "PTINR",
        "HEM",
        "زمن البروثرومبين",
        "Prothrombin time and INR",
        8000,
        "plasma",
        "Citrate",
        60,
        (
            num("PT", "زمن البروثرومبين", "Prothrombin time", "s", 1, "11.0", "13.5"),
            num("INR", "النسبة المعيارية", "INR", "", 2, "0.80", "1.20", None, "5.00"),
        ),
    ),
    LabTestDef(
        "SICKLE",
        "HEM",
        "اختبار المنجلية",
        "Sickling test",
        4000,
        "whole_blood",
        "EDTA",
        60,
        (posneg("SICK", "الخلايا المنجلية", "Sickle cells"),),
    ),
    LabTestDef(
        "BFMP",
        "MICRO",
        "فحص الملاريا (شريحة دم)",
        "Blood film for malaria",
        5000,
        "whole_blood",
        "EDTA",
        30,
        (posneg("MP", "طفيل الملاريا", "Malaria parasites"),),
        popularity=5,
    ),
    LabTestDef(
        "ICTMAL",
        "MICRO",
        "الفحص السريع للملاريا",
        "Malaria rapid test",
        4000,
        "whole_blood",
        "EDTA",
        20,
        (posneg("ICT", "مستضد الملاريا", "Malaria antigen"),),
        popularity=3,
    ),
    LabTestDef(
        "STOOL",
        "MICRO",
        "فحص البراز العام",
        "Stool general examination",
        4000,
        "stool",
        "Stool container",
        45,
        (
            Param(
                "CONS",
                "القوام",
                "Consistency",
                "",
                "choice",
                0,
                (Range(normal_text="formed"),),
                ("formed", "soft", "loose", "watery"),
            ),
            Param(
                "OVA",
                "البويضات والطفيليات",
                "Ova and parasites",
                "",
                "choice",
                0,
                (Range(normal_text="not seen"),),
                (
                    "not seen",
                    "Giardia lamblia",
                    "Entamoeba histolytica",
                    "Ascaris",
                    "Hymenolepis nana",
                ),
            ),
            num("PUS", "خلايا الصديد", "Pus cells", "/HPF", 0, None, "5"),
        ),
        popularity=3,
    ),
    LabTestDef(
        "UA",
        "MICRO",
        "فحص البول العام",
        "Urinalysis",
        5000,
        "urine",
        "Sterile container",
        45,
        (
            Param("COLOR", "اللون", "Colour", "", "text", 0, (Range(normal_text="yellow"),)),
            num("PH", "الأس الهيدروجيني", "pH", "", 1, "4.5", "8.0"),
            Param(
                "PROT", "البروتين", "Protein", "", "choice", 0, (Range(normal_text="nil"),), _GRADES
            ),
            Param("GLU", "السكر", "Glucose", "", "choice", 0, (Range(normal_text="nil"),), _GRADES),
            num("PUS", "خلايا الصديد", "Pus cells", "/HPF", 0, None, "5"),
        ),
        instructions_ar="عينة منتصف البول الصباحية",
        instructions_en="Early-morning midstream sample",
        popularity=4,
    ),
    LabTestDef(
        "UHCG",
        "MICRO",
        "اختبار الحمل في البول",
        "Urine pregnancy test",
        3000,
        "urine",
        "Sterile container",
        15,
        (posneg("HCG", "هرمون الحمل", "hCG"),),
        popularity=2,
    ),
    LabTestDef(
        "HPYLORI",
        "MICRO",
        "جرثومة المعدة (مستضد البراز)",
        "H. pylori stool antigen",
        8000,
        "stool",
        "Stool container",
        60,
        (posneg("HPAG", "مستضد الجرثومة الحلزونية", "H. pylori antigen"),),
        popularity=2,
    ),
    LabTestDef(
        "URINECS",
        "MICRO",
        "مزرعة البول",
        "Urine culture",
        15000,
        "urine",
        "Sterile container",
        2880,
        (
            Param(
                "CS",
                "نتيجة المزرعة",
                "Culture result",
                "",
                "text",
                0,
                (Range(normal_text="no growth"),),
            ),
        ),
    ),
    LabTestDef(
        "WIDAL",
        "SERO",
        "فحص الفيدال",
        "Widal test",
        5000,
        "serum",
        "Plain",
        60,
        (
            Param(
                "TO",
                "مستضد O",
                "S. typhi O",
                "",
                "choice",
                0,
                (Range(normal_text="<1:80"),),
                _TITRES,
            ),
            Param(
                "TH",
                "مستضد H",
                "S. typhi H",
                "",
                "choice",
                0,
                (Range(normal_text="<1:80"),),
                _TITRES,
            ),
        ),
        popularity=3,
    ),
    LabTestDef(
        "HBSAG",
        "SERO",
        "التهاب الكبد ب",
        "Hepatitis B surface antigen",
        6000,
        "serum",
        "Plain",
        60,
        (posneg("HBSAG", "المستضد السطحي", "HBsAg"),),
        popularity=2,
    ),
    LabTestDef(
        "HCV",
        "SERO",
        "التهاب الكبد ج",
        "Hepatitis C antibody",
        7000,
        "serum",
        "Plain",
        60,
        (posneg("HCVAB", "أجسام مضادة", "Anti-HCV"),),
    ),
    LabTestDef(
        "HPYAB",
        "SERO",
        "أجسام مضادة لجرثومة المعدة",
        "H. pylori antibody",
        7000,
        "serum",
        "Plain",
        60,
        (posneg("HPAB", "أجسام مضادة", "Anti-H. pylori"),),
    ),
    LabTestDef(
        "HIV",
        "SERO",
        "فيروس نقص المناعة",
        "HIV 1/2 antibody",
        6000,
        "serum",
        "Plain",
        60,
        (posneg("HIVAB", "أجسام مضادة", "Anti-HIV 1/2"),),
    ),
    LabTestDef(
        "VDRL",
        "SERO",
        "فحص الزهري",
        "VDRL",
        5000,
        "serum",
        "Plain",
        60,
        (posneg("VDRL", "VDRL", "VDRL"),),
    ),
    LabTestDef(
        "BRUC",
        "SERO",
        "فحص البروسيلا",
        "Brucella agglutination",
        6000,
        "serum",
        "Plain",
        60,
        (
            Param(
                "BRUC",
                "البروسيلا",
                "Brucella titre",
                "",
                "choice",
                0,
                (Range(normal_text="<1:80"),),
                _TITRES,
            ),
        ),
    ),
    LabTestDef(
        "CRP",
        "SERO",
        "البروتين المتفاعل",
        "C-reactive protein",
        7000,
        "serum",
        "Plain",
        60,
        (num("CRP", "البروتين المتفاعل", "CRP", "mg/L", 1, "0.0", "5.0"),),
        popularity=2,
    ),
    LabTestDef(
        "RF",
        "SERO",
        "عامل الروماتويد",
        "Rheumatoid factor",
        7000,
        "serum",
        "Plain",
        60,
        (num("RF", "عامل الروماتويد", "RF", "IU/mL", 0, None, "14"),),
    ),
    LabTestDef(
        "ASO",
        "SERO",
        "أجسام ضد الستربتوكوكس",
        "Antistreptolysin O",
        7000,
        "serum",
        "Plain",
        60,
        (num("ASO", "ASO", "ASO titre", "IU/mL", 0, None, "200"),),
    ),
    LabTestDef(
        "FBS",
        "CHEM",
        "سكر الدم الصائم",
        "Fasting blood sugar",
        4000,
        "plasma",
        "Fluoride",
        30,
        (num("GLU", "الجلوكوز", "Glucose", "mg/dL", 0, "70", "100", "40", "400"),),
        instructions_ar="صيام 8 ساعات على الأقل",
        instructions_en="Fast for at least 8 hours",
        popularity=4,
    ),
    LabTestDef(
        "RBS",
        "CHEM",
        "سكر الدم العشوائي",
        "Random blood sugar",
        3500,
        "plasma",
        "Fluoride",
        30,
        (num("GLU", "الجلوكوز", "Glucose", "mg/dL", 0, "70", "140", "40", "400"),),
        popularity=4,
    ),
    LabTestDef(
        "PPBS",
        "CHEM",
        "سكر الدم بعد الأكل",
        "Two-hour postprandial glucose",
        4000,
        "plasma",
        "Fluoride",
        30,
        (num("GLU", "الجلوكوز", "Glucose", "mg/dL", 0, "70", "140", "40", "400"),),
        instructions_ar="بعد ساعتين من الوجبة",
        instructions_en="Two hours after a meal",
    ),
    LabTestDef(
        "HBA1C",
        "CHEM",
        "السكر التراكمي",
        "Glycated hemoglobin (HbA1c)",
        15000,
        "whole_blood",
        "EDTA",
        120,
        (num("A1C", "السكر التراكمي", "HbA1c", "%", 1, "4.0", "5.6"),),
        popularity=3,
    ),
    LabTestDef(
        "RFT",
        "CHEM",
        "وظائف الكلى",
        "Renal function (urea, creatinine)",
        9000,
        "serum",
        "Plain",
        120,
        (
            num("UREA", "اليوريا", "Urea", "mg/dL", 0, "15", "45", None, "200"),
            sexed(
                "CREAT", "الكرياتينين", "Creatinine", "mg/dL", 2, ("0.70", "1.30"), ("0.60", "1.10")
            ),
        ),
        popularity=3,
    ),
    LabTestDef(
        "ELEC",
        "CHEM",
        "الأملاح",
        "Electrolytes (Na, K, Cl)",
        12000,
        "serum",
        "Plain",
        120,
        (
            num("NA", "الصوديوم", "Sodium", "mmol/L", 0, "135", "145", "120", "160"),
            num("K", "البوتاسيوم", "Potassium", "mmol/L", 1, "3.5", "5.1", "2.5", "6.5"),
            num("CL", "الكلوريد", "Chloride", "mmol/L", 0, "98", "107"),
        ),
        popularity=2,
    ),
    LabTestDef(
        "LFT",
        "CHEM",
        "وظائف الكبد",
        "Liver function tests",
        18000,
        "serum",
        "Plain",
        120,
        (
            num("ALT", "إنزيم ALT", "ALT", "U/L", 0, "7", "56"),
            num("AST", "إنزيم AST", "AST", "U/L", 0, "10", "40"),
            num("ALP", "الفوسفاتيز القلوي", "Alkaline phosphatase", "U/L", 0, "44", "147"),
            num(
                "TBIL",
                "البيليروبين الكلي",
                "Total bilirubin",
                "mg/dL",
                1,
                "0.1",
                "1.2",
                None,
                "15.0",
            ),
            num("DBIL", "البيليروبين المباشر", "Direct bilirubin", "mg/dL", 1, "0.0", "0.3"),
            num("ALB", "الألبومين", "Albumin", "g/dL", 1, "3.5", "5.0"),
            num("TP", "البروتين الكلي", "Total protein", "g/dL", 1, "6.0", "8.3"),
        ),
        popularity=2,
    ),
    LabTestDef(
        "LIPID",
        "CHEM",
        "دهون الدم",
        "Lipid profile",
        15000,
        "serum",
        "Plain",
        120,
        (
            num("TC", "الكوليسترول الكلي", "Total cholesterol", "mg/dL", 0, None, "200"),
            num("TG", "الدهون الثلاثية", "Triglycerides", "mg/dL", 0, None, "150"),
            num("HDL", "الكوليسترول النافع", "HDL cholesterol", "mg/dL", 0, "40", None),
            num("LDL", "الكوليسترول الضار", "LDL cholesterol", "mg/dL", 0, None, "130"),
        ),
        instructions_ar="صيام 12 ساعة",
        instructions_en="Fast for 12 hours",
        popularity=2,
    ),
    LabTestDef(
        "URIC",
        "CHEM",
        "حمض اليوريك",
        "Uric acid",
        5000,
        "serum",
        "Plain",
        60,
        (sexed("URIC", "حمض اليوريك", "Uric acid", "mg/dL", 1, ("3.4", "7.0"), ("2.4", "6.0")),),
    ),
    LabTestDef(
        "CA",
        "CHEM",
        "الكالسيوم",
        "Calcium",
        5000,
        "serum",
        "Plain",
        60,
        (num("CA", "الكالسيوم", "Calcium", "mg/dL", 1, "8.5", "10.5", "6.0", "13.0"),),
    ),
    LabTestDef(
        "PHOS",
        "CHEM",
        "الفوسفور",
        "Phosphate",
        5000,
        "serum",
        "Plain",
        60,
        (num("PHOS", "الفوسفور", "Phosphate", "mg/dL", 1, "2.5", "4.5"),),
    ),
    LabTestDef(
        "MG",
        "CHEM",
        "المغنيسيوم",
        "Magnesium",
        6000,
        "serum",
        "Plain",
        60,
        (num("MG", "المغنيسيوم", "Magnesium", "mg/dL", 1, "1.7", "2.2"),),
    ),
    LabTestDef(
        "AMYL",
        "CHEM",
        "الأميليز",
        "Amylase",
        9000,
        "serum",
        "Plain",
        60,
        (num("AMYL", "الأميليز", "Amylase", "U/L", 0, "30", "110"),),
    ),
    LabTestDef(
        "GGT",
        "CHEM",
        "إنزيم GGT",
        "Gamma-GT",
        7000,
        "serum",
        "Plain",
        60,
        (num("GGT", "إنزيم GGT", "GGT", "U/L", 0, "9", "48"),),
    ),
    LabTestDef(
        "LDH",
        "CHEM",
        "إنزيم LDH",
        "Lactate dehydrogenase",
        9000,
        "serum",
        "Plain",
        60,
        (num("LDH", "إنزيم LDH", "LDH", "U/L", 0, "140", "280"),),
    ),
    LabTestDef(
        "IRON",
        "CHEM",
        "الحديد",
        "Serum iron",
        9000,
        "serum",
        "Plain",
        120,
        (num("FE", "الحديد", "Iron", "ug/dL", 0, "60", "170"),),
    ),
    LabTestDef(
        "FERR",
        "CHEM",
        "مخزون الحديد",
        "Ferritin",
        15000,
        "serum",
        "Plain",
        240,
        (sexed("FERR", "الفيريتين", "Ferritin", "ng/mL", 0, ("24", "336"), ("11", "307")),),
    ),
    LabTestDef(
        "VITD",
        "CHEM",
        "فيتامين د",
        "Vitamin D (25-OH)",
        25000,
        "serum",
        "Plain",
        1440,
        (num("VITD", "فيتامين د", "25-OH vitamin D", "ng/mL", 1, "30.0", "100.0"),),
    ),
    LabTestDef(
        "B12",
        "CHEM",
        "فيتامين ب12",
        "Vitamin B12",
        20000,
        "serum",
        "Plain",
        1440,
        (num("B12", "فيتامين ب12", "Vitamin B12", "pg/mL", 0, "200", "900"),),
    ),
    LabTestDef(
        "TROP",
        "CHEM",
        "التروبونين",
        "Troponin I",
        20000,
        "serum",
        "Plain",
        60,
        (num("TNI", "التروبونين", "Troponin I", "ng/mL", 2, None, "0.04", None, "0.40"),),
    ),
    LabTestDef(
        "CKMB",
        "CHEM",
        "إنزيم القلب CK-MB",
        "CK-MB",
        12000,
        "serum",
        "Plain",
        60,
        (num("CKMB", "CK-MB", "CK-MB", "U/L", 0, "0", "25"),),
    ),
    LabTestDef(
        "TSH",
        "HORM",
        "الهرمون المنبه للغدة الدرقية",
        "Thyroid stimulating hormone",
        15000,
        "serum",
        "Plain",
        240,
        (num("TSH", "TSH", "TSH", "mIU/L", 2, "0.40", "4.00"),),
        popularity=2,
    ),
    LabTestDef(
        "FT4",
        "HORM",
        "هرمون الغدة الدرقية الحر",
        "Free T4",
        15000,
        "serum",
        "Plain",
        240,
        (num("FT4", "FT4", "Free T4", "ng/dL", 2, "0.80", "1.80"),),
    ),
    LabTestDef(
        "PSA",
        "HORM",
        "مستضد البروستاتا",
        "Prostate specific antigen",
        15000,
        "serum",
        "Plain",
        240,
        (num("PSA", "PSA", "PSA", "ng/mL", 2, "0.00", "4.00"),),
    ),
    LabTestDef(
        "BHCG",
        "HORM",
        "هرمون الحمل في الدم",
        "Serum beta hCG",
        12000,
        "serum",
        "Plain",
        120,
        (num("BHCG", "بيتا hCG", "Beta hCG", "mIU/mL", 1, "0.0", "5.0"),),
    ),
    LabTestDef(
        "PRL",
        "HORM",
        "هرمون الحليب",
        "Prolactin",
        15000,
        "serum",
        "Plain",
        240,
        (sexed("PRL", "البرولاكتين", "Prolactin", "ng/mL", 1, ("4.0", "15.2"), ("4.8", "23.3")),),
    ),
)


# --- clinical scenarios -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rx:
    drug: str
    #: Base units per dose (None for bottles, tubes and the like: then ``quantity`` is given).
    dose_quantity: str | None
    dose: str
    frequency: str
    days: int
    quantity: int | None = None
    route: str = "oral"


@dataclass(frozen=True, slots=True)
class Scenario:
    icd10: str
    text_en: str
    complaint_ar: str
    plan_ar: str
    weight: int
    labs: tuple[str, ...] = ()
    procedures: tuple[str, ...] = ()
    rx: tuple[Rx, ...] = ()
    #: Labs / procedures / drugs added only sometimes.
    extra_labs: tuple[str, ...] = ()
    children: bool = False
    adults_only: bool = False


_PARA = Rx("PARA500", "2", "1 g", "TID", 3)
_PARA_SYR = Rx("PARASYR", None, "5 ml", "TID", 3, 1)

SCENARIOS: dict[str, tuple[Scenario, ...]] = {
    "GEN": (
        Scenario(
            "B54",
            "Malaria",
            "حمى ورعشة وصداع منذ يومين",
            "علاج الملاريا والمتابعة بعد ثلاثة أيام",
            9,
            labs=("BFMP",),
            rx=(Rx("COART", "4", "4 tablets", "BID", 3), _PARA),
            extra_labs=("CBC",),
        ),
        Scenario(
            "J02.9",
            "Acute pharyngitis",
            "ألم في الحلق وحرارة",
            "مضاد حيوي وخافض حرارة",
            6,
            rx=(Rx("AMOX500", "1", "500 mg", "TID", 7), _PARA),
        ),
        Scenario(
            "K29.7",
            "Gastritis",
            "ألم في أعلى البطن وحموضة",
            "مثبط حموضة لمدة أسبوعين",
            5,
            rx=(Rx("OMEP20", "1", "20 mg", "BID", 14), Rx("ANTACID", None, "10 ml", "TID", 7, 1)),
            extra_labs=("HPYLORI",),
        ),
        Scenario(
            "A01.0",
            "Typhoid fever",
            "حمى مستمرة لأسبوع وآلام في البطن",
            "مضاد حيوي ومتابعة",
            4,
            labs=("WIDAL", "CBC"),
            rx=(Rx("CIPRO500", "1", "500 mg", "BID", 7), _PARA),
        ),
        Scenario(
            "N30.0",
            "Acute cystitis",
            "حرقان في البول وتكرار التبول",
            "مضاد حيوي وسوائل كثيرة",
            5,
            labs=("UA",),
            rx=(Rx("NITRO100", "1", "100 mg", "BID", 5),),
        ),
        Scenario(
            "A06.0",
            "Amoebic dysentery",
            "إسهال مع مخاط ومغص",
            "علاج الأميبا وأملاح الإرواء",
            4,
            labs=("STOOL",),
            rx=(Rx("METRO500", "1", "500 mg", "TID", 5), Rx("ORS", "1", "1 sachet", "TID", 3)),
        ),
        Scenario(
            "M54.5",
            "Low back pain",
            "ألم أسفل الظهر منذ أسبوع",
            "مسكن وحقنة وراحة",
            4,
            procedures=("PRC-INJ",),
            rx=(
                Rx("DICLO50", "1", "50 mg", "BID", 5),
                Rx("DICLOINJ", "1", "75 mg", "STAT", 1, 1, "im"),
            ),
        ),
        Scenario(
            "T14.1",
            "Open wound",
            "جرح في اليد",
            "خياطة الجرح ولقاح التيتانوس",
            2,
            procedures=("PRC-SUTURE",),
            rx=(
                Rx("COAMOX625", "1", "625 mg", "BID", 5),
                Rx("TETANUS", "1", "0.5 ml", "STAT", 1, 1, "im"),
            ),
            adults_only=True,
        ),
        Scenario(
            "R51",
            "Headache",
            "صداع متكرر",
            "مسكن ومتابعة الضغط",
            3,
            rx=(_PARA,),
            extra_labs=("CBC",),
        ),
        Scenario(
            "J30.4",
            "Allergic rhinitis",
            "عطس وسيلان أنف",
            "مضاد حساسية",
            3,
            rx=(Rx("CETI10", "1", "10 mg", "OD", 10),),
        ),
    ),
    "INT": (
        Scenario(
            "I10",
            "Essential hypertension",
            "متابعة ضغط الدم",
            "الاستمرار على العلاج وقياس الضغط في المنزل",
            8,
            labs=("RFT",),
            procedures=("PRC-ECG",),
            rx=(Rx("AMLO5", "1", "5 mg", "OD", 30),),
            extra_labs=("ELEC", "LIPID"),
            adults_only=True,
        ),
        Scenario(
            "E11.9",
            "Type 2 diabetes mellitus",
            "متابعة السكري",
            "ضبط السكر والحمية",
            8,
            labs=("FBS", "HBA1C"),
            rx=(Rx("METF500", "1", "500 mg", "BID", 30),),
            extra_labs=("RFT", "LIPID"),
            adults_only=True,
        ),
        Scenario(
            "E78.5",
            "Hyperlipidaemia",
            "ارتفاع الدهون",
            "دواء خافض للدهون وحمية",
            3,
            labs=("LIPID",),
            rx=(Rx("ATOR20", "1", "20 mg", "HS", 30),),
            adults_only=True,
        ),
        Scenario(
            "I50.9",
            "Heart failure",
            "ضيق تنفس وتورم القدمين",
            "مدر للبول ومتابعة",
            2,
            labs=("RFT", "ELEC"),
            procedures=("PRC-ECG",),
            rx=(Rx("FURO40", "1", "40 mg", "OD", 30), Rx("ENAL10", "1", "10 mg", "OD", 30)),
            adults_only=True,
        ),
        Scenario(
            "D50.9",
            "Iron deficiency anaemia",
            "إرهاق ودوخة",
            "حديد وحمض الفوليك",
            4,
            labs=("CBC",),
            rx=(Rx("FEFOL", "1", "1 tablet", "OD", 30),),
            extra_labs=("FERR",),
        ),
        Scenario(
            "J45.9",
            "Asthma",
            "ضيق تنفس وصفير",
            "بخار وبخاخ موسع للشعب",
            3,
            procedures=("PRC-NEB",),
            rx=(
                Rx("SALBINH", None, "2 puffs", "QID", 30, 1, "inhaled"),
                Rx("PRED5", "6", "30 mg", "OD", 5),
            ),
        ),
        Scenario(
            "K76.0",
            "Fatty liver",
            "ألم في الجانب الأيمن",
            "حمية ومتابعة وظائف الكبد",
            2,
            labs=("LFT",),
            extra_labs=("HBSAG",),
            adults_only=True,
        ),
        Scenario(
            "N18.9",
            "Chronic kidney disease",
            "متابعة وظائف الكلى",
            "متابعة دورية وضبط الضغط",
            2,
            labs=("RFT", "ELEC", "CBC"),
            rx=(Rx("CALCD3", "1", "1 tablet", "OD", 30),),
            adults_only=True,
        ),
        Scenario(
            "E03.9",
            "Hypothyroidism",
            "خمول وزيادة وزن",
            "فحص الغدة والمتابعة",
            2,
            labs=("TSH", "FT4"),
            adults_only=True,
        ),
    ),
    "PED": (
        Scenario(
            "B54",
            "Malaria",
            "حمى وقيء",
            "علاج الملاريا للأطفال",
            8,
            labs=("BFMP",),
            rx=(Rx("COARTDISP", "2", "2 tablets", "BID", 3), _PARA_SYR),
            children=True,
        ),
        Scenario(
            "J18.9",
            "Pneumonia",
            "كحة وحرارة وسرعة تنفس",
            "مضاد حيوي ومتابعة بعد يومين",
            5,
            labs=("CBC",),
            procedures=("PRC-NEB",),
            rx=(Rx("AMOXSYR", None, "5 ml", "TID", 7, 2), _PARA_SYR),
            children=True,
        ),
        Scenario(
            "A08.4",
            "Viral gastroenteritis",
            "إسهال وقيء",
            "أملاح الإرواء والزنك",
            7,
            rx=(Rx("ORS", "1", "1 sachet", "TID", 5), Rx("ZINC20", "1", "20 mg", "OD", 10)),
            extra_labs=("STOOL",),
            children=True,
        ),
        Scenario(
            "J03.9",
            "Acute tonsillitis",
            "ألم في الحلق وحرارة",
            "مضاد حيوي وخافض حرارة",
            5,
            rx=(Rx("AZISYR", None, "5 ml", "OD", 3, 1), _PARA_SYR),
            children=True,
        ),
        Scenario(
            "H66.9",
            "Otitis media",
            "ألم في الأذن",
            "مضاد حيوي ومسكن",
            3,
            rx=(
                Rx("AMOXSYR250", None, "5 ml", "TID", 7, 1),
                Rx("IBUSYR", None, "5 ml", "TID", 3, 1),
            ),
            children=True,
        ),
        Scenario(
            "B82.9",
            "Intestinal parasitism",
            "مغص وفقدان شهية",
            "طارد للديدان",
            4,
            labs=("STOOL",),
            rx=(Rx("ALBENSYR", None, "10 ml", "STAT", 1, 1),),
            children=True,
        ),
        Scenario(
            "Z00.1",
            "Routine child health examination",
            "متابعة النمو",
            "فيتامينات ومتابعة التطعيمات",
            3,
            rx=(Rx("MULTISYR", None, "5 ml", "OD", 30, 1),),
            children=True,
        ),
        Scenario(
            "J21.9",
            "Acute bronchiolitis",
            "صفير وصعوبة في التنفس",
            "جلسة بخار ومتابعة",
            3,
            procedures=("PRC-NEB",),
            rx=(Rx("SALINDROP", None, "2 drops", "QID", 5, 1, "nasal"),),
            children=True,
        ),
    ),
    "GYN": (
        Scenario(
            "Z34.9",
            "Supervision of normal pregnancy",
            "متابعة حمل",
            "متابعة دورية وحديد وحمض الفوليك",
            9,
            labs=("CBC", "UA"),
            procedures=("GYN-US",),
            rx=(Rx("FEFOL", "1", "1 tablet", "OD", 30), Rx("FOLIC5", "1", "5 mg", "OD", 30)),
            extra_labs=("BG", "HBSAG", "RBS"),
            adults_only=True,
        ),
        Scenario(
            "N76.0",
            "Acute vaginitis",
            "إفرازات مهبلية وحكة",
            "علاج موضعي وفموي",
            5,
            rx=(
                Rx("CLOTRIVAG", "1", "500 mg", "STAT", 1, 1, "other"),
                Rx("METRO500", "1", "500 mg", "BID", 7),
            ),
            adults_only=True,
        ),
        Scenario(
            "N94.6",
            "Dysmenorrhoea",
            "ألم مع الدورة الشهرية",
            "مسكن ومتابعة",
            4,
            rx=(Rx("MEFEN500", "1", "500 mg", "TID", 3),),
            extra_labs=("UHCG",),
            adults_only=True,
        ),
        Scenario(
            "O20.0",
            "Threatened abortion",
            "نزيف بسيط في الحمل المبكر",
            "راحة ومثبت حمل ومتابعة بالموجات",
            2,
            labs=("BHCG",),
            procedures=("GYN-US",),
            rx=(Rx("DYDRO10", "1", "10 mg", "BID", 14),),
            adults_only=True,
        ),
        Scenario(
            "O21.0",
            "Mild hyperemesis gravidarum",
            "قيء متكرر في الحمل",
            "محلول وريدي ومضاد للقيء",
            2,
            labs=("UA", "ELEC"),
            procedures=("PRC-CANNULA", "PRC-DRIP"),
            rx=(
                Rx("NS500", "1", "500 ml", "STAT", 1, 2, "iv"),
                Rx("ONDAN4", "1", "4 mg", "BID", 3),
            ),
            adults_only=True,
        ),
        Scenario(
            "N83.2",
            "Ovarian cyst",
            "ألم في الحوض",
            "موجات صوتية ومتابعة",
            2,
            procedures=("GYN-PELVUS",),
            rx=(Rx("IBU400", "1", "400 mg", "TID", 5),),
            adults_only=True,
        ),
    ),
    "DEN": (
        Scenario(
            "K02.9",
            "Dental caries",
            "ألم في الضرس",
            "حشوة",
            8,
            procedures=("DEN-XRAY", "DEN-FILL"),
            rx=(Rx("IBU400", "1", "400 mg", "TID", 3),),
        ),
        Scenario(
            "K04.7",
            "Periapical abscess",
            "تورم وألم في اللثة",
            "خلع ومضاد حيوي",
            5,
            procedures=("DEN-EXT",),
            rx=(
                Rx("AMOX500", "1", "500 mg", "TID", 5),
                Rx("METRO500", "1", "500 mg", "TID", 5),
                Rx("LIDODENT", "1", "1 cartridge", "STAT", 1, 1, "other"),
            ),
        ),
        Scenario(
            "K05.1",
            "Chronic gingivitis",
            "نزيف اللثة",
            "تنظيف الجير وغسول فم",
            4,
            procedures=("DEN-SCALE",),
            rx=(Rx("CHXMW", None, "10 ml", "BID", 14, 1, "other"),),
        ),
        Scenario(
            "K02.9",
            "Dental caries (deep)",
            "ألم شديد في الضرس ليلاً",
            "علاج عصب على جلستين",
            2,
            procedures=("DEN-XRAY", "DEN-RCT"),
            rx=(Rx("IBU400", "1", "400 mg", "TID", 5),),
            adults_only=True,
        ),
    ),
}

#: Substitutes a doctor picks for a drug the patient is allergic to.
ALLERGY_SUBSTITUTES: dict[str, str] = {
    "AMOX500": "AZI500",
    "AMOX250": "AZI250",
    "AMOXSYR": "AZISYR",
    "AMOXSYR250": "AZISYR",
    "COAMOX625": "CLARI500",
    "IBU400": "PARA500",
    "IBUSYR": "PARASYR",
    "DICLO50": "PARA500",
    "DICLOINJ": "METAMINJ",
    "MEFEN500": "PARA500",
    "CIPRO500": "COTRI960",
    "COTRI960": "NITRO100",
}
