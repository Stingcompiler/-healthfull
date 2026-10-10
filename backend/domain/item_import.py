"""Stock item, batch and opening stock import rows (FEATURES 8.13), no database.

One sheet row per batch: the item columns describe the stock item of a drug or consumable
catalog service (created when the code is new), the batch columns an opening stock quantity
of one batch in one store. Several rows may share a service code to give an item several
batches; the first row of a code defines the item and later rows may leave the item columns
blank (a later value that differs is ``IMPORT_ITEM_CONFLICT``).

What the database knows comes in as ``services`` (code to :class:`KnownService`) and
``stores`` (active store codes); duplicates against existing batches and stock are found by
the service (``apps.imports.services``).

Error codes are the pharmacy and catalog ones (``INVALID_CODE``, ``SERVICE_NAME_REQUIRED``,
``SERVICE_KIND_UNKNOWN``, ``SERVICE_NOT_STOCKABLE``, ``NAME_REQUIRED``, ``UNIT_REQUIRED``,
``INVALID_FORM``, ``INVALID_STORAGE``, ``INVALID_QUANTITY``, ``INVALID_CONVERSION``,
``BATCH_NO_REQUIRED``, ``BATCH_EXPIRED``, ``INVALID_COST``) plus ``EXPIRY_REQUIRED``,
``INVALID_EXPIRY_DATE``, ``STORE_UNKNOWN``, ``VALUE_TOO_LONG``, ``FORMULA_NOT_ALLOWED``,
``IMPORT_ITEM_CONFLICT`` and ``IMPORT_ITEM_INVALID`` (the row that defines the item has
errors, so its other batches cannot be imported either).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from domain import sheet
from domain.sheet import Column

__all__ = [
    "BATCH_KEYS",
    "COLUMNS",
    "ITEM_KEYS",
    "ItemRow",
    "KnownService",
    "parse_rows",
]

COLUMNS: tuple[Column, ...] = (
    Column("service_code", "Service code", "رمز الخدمة", 40, ("code", "item code"), True),
    Column("name_ar", "Name (Arabic)", "الاسم بالعربية", 200, ("arabic name",)),
    Column("name_en", "Name (English)", "الاسم بالإنجليزية", 200, ("english name", "name")),
    Column("kind", "Kind (drug or consumable)", "النوع (دواء أو مستهلك)", 20, ("kind", "النوع")),
    Column("generic_name", "Generic name", "الاسم العلمي", 200, ("generic",)),
    Column(
        "generic_name_ar",
        "Generic name (Arabic)",
        "الاسم العلمي بالعربية",
        200,
        ("arabic generic name",),
    ),
    Column("brand_name", "Brand name", "الاسم التجاري", 200, ("brand",)),
    Column("form", "Form", "الشكل الصيدلاني", 30),
    Column("strength", "Strength", "التركيز", 60),
    Column("base_unit_code", "Base unit code", "رمز الوحدة الصغرى", 20, ("base unit",)),
    Column("base_unit_name_ar", "Base unit (Arabic)", "الوحدة الصغرى بالعربية", 50),
    Column("base_unit_name_en", "Base unit (English)", "الوحدة الصغرى بالإنجليزية", 50),
    Column("pack_unit_code", "Pack unit code", "رمز العبوة", 20, ("pack unit",)),
    Column("pack_unit_name_ar", "Pack unit (Arabic)", "العبوة بالعربية", 50),
    Column("pack_unit_name_en", "Pack unit (English)", "العبوة بالإنجليزية", 50),
    Column("pack_factor", "Base units per pack", "عدد الوحدات في العبوة", 10, ("factor",)),
    Column("min_stock", "Minimum stock", "الحد الأدنى للمخزون", 14),
    Column("reorder_qty", "Reorder quantity", "كمية إعادة الطلب", 14),
    Column("storage", "Storage", "التخزين", 30),
    Column("barcode", "Barcode", "الباركود", 60),
    Column("batch_no", "Batch number", "رقم التشغيلة", 60, ("batch", "lot")),
    Column("expiry_date", "Expiry date", "تاريخ الانتهاء", 20, ("expiry",)),
    Column(
        "quantity",
        "Opening quantity (base units)",
        "الكمية الافتتاحية (بالوحدة الصغرى)",
        14,
        ("quantity", "qty", "الكمية"),
    ),
    Column(
        "unit_cost", "Unit cost (per base unit)", "التكلفة للوحدة الصغرى", 20, ("cost", "التكلفة")
    ),
    Column("store", "Store code", "رمز المخزن", 20, ("store", "المخزن")),
)

#: Columns that describe the item (taken from the first row of a service code).
ITEM_KEYS: tuple[str, ...] = (
    "name_ar",
    "name_en",
    "kind",
    "generic_name",
    "generic_name_ar",
    "brand_name",
    "form",
    "strength",
    "base_unit_code",
    "base_unit_name_ar",
    "base_unit_name_en",
    "pack_unit_code",
    "pack_unit_name_ar",
    "pack_unit_name_en",
    "pack_factor",
    "min_stock",
    "reorder_qty",
    "storage",
    "barcode",
)
#: Columns of the batch and its opening quantity.
BATCH_KEYS: tuple[str, ...] = ("batch_no", "expiry_date", "quantity", "unit_cost", "store")

_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.-]{0,39}\Z")
_UNIT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,20}\Z")

_KINDS = {
    "drug": "drug",
    "medicine": "drug",
    "دواء": "drug",
    "ادوية": "drug",
    "أدوية": "drug",
    "consumable": "consumable",
    "supply": "consumable",
    "مستهلك": "consumable",
    "مستهلكات": "consumable",
}
_FORMS = {
    "tablet": "tablet",
    "tab": "tablet",
    "قرص": "tablet",
    "أقراص": "tablet",
    "اقراص": "tablet",
    "capsule": "capsule",
    "cap": "capsule",
    "كبسولة": "capsule",
    "كبسولات": "capsule",
    "syrup": "syrup",
    "شراب": "syrup",
    "suspension": "suspension",
    "معلق": "suspension",
    "injection": "injection",
    "inj": "injection",
    "حقنة": "injection",
    "حقن": "injection",
    "infusion": "infusion",
    "محلول وريدي": "infusion",
    "cream": "cream",
    "ointment": "cream",
    "cream or ointment": "cream",
    "كريم": "cream",
    "مرهم": "cream",
    "drops": "drops",
    "قطرة": "drops",
    "inhaler": "inhaler",
    "بخاخ": "inhaler",
    "suppository": "suppository",
    "تحاميل": "suppository",
    "لبوس": "suppository",
    "sachet": "sachet",
    "ظرف": "sachet",
    "أكياس": "sachet",
    "supply": "supply",
    "medical supply": "supply",
    "مستلزم": "supply",
    "مستلزمات": "supply",
    "other": "other",
    "أخرى": "other",
    "اخرى": "other",
}
_STORAGE = {
    "room": "room",
    "room temperature": "room",
    "حرارة الغرفة": "room",
    "cool": "cool",
    "cool place": "cool",
    "مكان بارد": "cool",
    "fridge": "fridge",
    "refrigerated": "fridge",
    "refrigerated (2-8 c)": "fridge",
    "ثلاجة": "fridge",
    "frozen": "frozen",
    "مجمد": "frozen",
}


@dataclass(frozen=True, slots=True)
class KnownService:
    """A catalog service code already in the database."""

    kind: str
    has_item: bool


@dataclass(slots=True)
class ItemRow:
    """One sheet row read into item and batch data, with its errors and hints."""

    row_no: int
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    #: The cells as read (text), before parsing.
    raw: dict[str, str] = field(default_factory=dict)
    #: The first row of its service code (it creates the item when the code is new).
    defines_item: bool = False
    has_batch: bool = False

    def add_error(self, code: str, field_name: str) -> None:
        entry = {"code": code, "field": field_name}
        if entry not in self.errors:
            self.errors.append(entry)


def _lookup(table: Mapping[str, str], raw: str) -> str | None:
    return table.get(" ".join(raw.lower().split()))


def _read_texts(row: ItemRow, cells: Mapping[str, Any]) -> None:
    for column in COLUMNS:
        raw = cells.get(column.key)
        if sheet.is_formula(raw):
            row.add_error("FORMULA_NOT_ALLOWED", column.key)
            raw = None
        value = sheet.text(raw)
        if len(value) > column.max_length:
            row.add_error("VALUE_TOO_LONG", column.key)
            value = value[: column.max_length]
        row.data[column.key] = value
    row.raw = dict(row.data)


def _whole(row: ItemRow, key: str, *, minimum: int, code: str = "INVALID_QUANTITY") -> None:
    try:
        row.data[key] = sheet.parse_whole(row.data[key], minimum=minimum)
    except ValueError:
        row.add_error(code, key)
        row.data[key] = None


def _parse_item(row: ItemRow, known: KnownService | None) -> None:
    data = row.data
    if known is not None and known.has_item:
        row.warnings.append({"code": "item_exists"})
        return
    if known is None:
        if not (data["name_ar"] or data["name_en"]):
            row.add_error("SERVICE_NAME_REQUIRED", "name_ar")
        kind = _lookup(_KINDS, data["kind"]) if data["kind"] else "drug"
        if kind is None:
            row.add_error("SERVICE_KIND_UNKNOWN", "kind")
            kind = "drug"
        data["kind"] = kind
    else:
        if known.kind not in ("drug", "consumable"):
            row.add_error("SERVICE_NOT_STOCKABLE", "service_code")
        data["kind"] = known.kind
    if not data["generic_name"]:
        data["generic_name"] = data["name_en"] or data["name_ar"]
    if not data["generic_name"]:
        row.add_error("NAME_REQUIRED", "generic_name")
    if not data["base_unit_code"]:
        row.add_error("UNIT_REQUIRED", "base_unit_code")
    elif not _UNIT_RE.match(data["base_unit_code"]):
        row.add_error("INVALID_CONVERSION", "base_unit_code")
    for lang in ("ar", "en"):
        key = f"base_unit_name_{lang}"
        data[key] = data[key] or data["base_unit_code"]

    default_form = "supply" if data["kind"] == "consumable" else "tablet"
    form = _lookup(_FORMS, data["form"]) if data["form"] else default_form
    if form is None:
        row.add_error("INVALID_FORM", "form")
    data["form"] = form or default_form
    storage = _lookup(_STORAGE, data["storage"]) if data["storage"] else "room"
    if storage is None:
        row.add_error("INVALID_STORAGE", "storage")
    data["storage"] = storage or "room"
    _whole(row, "min_stock", minimum=0)
    _whole(row, "reorder_qty", minimum=0)

    pack_given = any(data[k] for k in ("pack_unit_code", "pack_factor"))
    _whole(row, "pack_factor", minimum=2, code="INVALID_CONVERSION")
    if pack_given:
        code = data["pack_unit_code"]
        if (
            not code
            or not _UNIT_RE.match(code)
            or code == data["base_unit_code"]
            or data["pack_factor"] is None
        ):
            row.add_error("INVALID_CONVERSION", "pack_unit_code" if not code else "pack_factor")
        for lang in ("ar", "en"):
            key = f"pack_unit_name_{lang}"
            data[key] = data[key] or code


def _parse_batch(
    row: ItemRow, *, today: date, stores: frozenset[str], default_store: str | None
) -> None:
    data = row.data
    row.has_batch = any(data[k] for k in ("batch_no", "expiry_date", "quantity", "unit_cost"))
    if not row.has_batch:
        for key in ("expiry_date", "quantity", "unit_cost"):
            data[key] = None
        data["store"] = ""
        return
    if not data["batch_no"]:
        row.add_error("BATCH_NO_REQUIRED", "batch_no")
    try:
        expiry = sheet.parse_date(data["expiry_date"])
    except ValueError:
        row.add_error("INVALID_EXPIRY_DATE", "expiry_date")
        expiry = None
    if expiry is None and "expiry_date" not in {e["field"] for e in row.errors}:
        row.add_error("EXPIRY_REQUIRED", "expiry_date")
    elif expiry is not None and expiry < today:
        row.add_error("BATCH_EXPIRED", "expiry_date")
    data["expiry_date"] = expiry.isoformat() if expiry is not None else None
    _whole(row, "quantity", minimum=1)
    if data["quantity"] is None and "quantity" not in {e["field"] for e in row.errors}:
        row.add_error("INVALID_QUANTITY", "quantity")
    try:
        cost = sheet.parse_decimal(data["unit_cost"], places=4)
    except ValueError:
        row.add_error("INVALID_COST", "unit_cost")
        cost = None
    data["unit_cost"] = str(cost) if cost is not None else "0.0000"
    store = (data["store"] or default_store or "").upper()
    if not store or store not in stores:
        row.add_error("STORE_UNKNOWN", "store")
    data["store"] = store


def parse_rows(
    rows: Sequence[tuple[int, Mapping[str, Any]]],
    *,
    today: date,
    services: Mapping[str, KnownService],
    stores: frozenset[str],
    default_store: str | None = None,
) -> list[ItemRow]:
    """Read every non-blank row (``(sheet row number, field key to cell)``) of an item sheet.

    ``services`` maps existing catalog codes (upper case) to what is known about them,
    ``stores`` holds the active store codes (upper case) and ``default_store`` applies to
    batch rows without a store.
    """
    out: list[ItemRow] = []
    first_of: dict[str, ItemRow] = {}
    batch_seen: dict[tuple[str, str, str], int] = {}
    for row_no, cells in rows:
        if all(sheet.text(v) == "" for v in cells.values()):
            continue
        row = ItemRow(row_no)
        _read_texts(row, cells)
        code = row.data["service_code"].upper()
        row.data["service_code"] = code
        if not code:
            row.add_error("CODE_REQUIRED", "service_code")
        elif not _CODE_RE.match(code):
            row.add_error("INVALID_CODE", "service_code")
        first = first_of.get(code) if code else None
        if first is None:
            row.defines_item = True
            _parse_item(row, services.get(code))
            if code:
                first_of[code] = row
        else:
            for key in ITEM_KEYS:
                given = row.data[key]
                if given and given.lower() != first.raw.get(key, "").lower():
                    row.add_error("IMPORT_ITEM_CONFLICT", key)
                row.data[key] = first.data.get(key)
            if first.errors:
                row.add_error("IMPORT_ITEM_INVALID", "service_code")
            row.warnings.extend(w for w in first.warnings if w["code"] == "item_exists")
        _parse_batch(row, today=today, stores=stores, default_store=default_store)
        if row.has_batch and not row.errors:
            batch_key = (code, row.data["batch_no"].upper(), str(row.data["expiry_date"]))
            if batch_key in batch_seen:
                row.warnings.append({"code": "in_file", "row_no": batch_seen[batch_key]})
            else:
                batch_seen[batch_key] = row_no
        out.append(row)
    return out
