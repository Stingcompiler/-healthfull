/** Shared helpers of the ops specs (imports, notifications, status, audit, export). */
import { fixture } from "../../helpers";

const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

export interface UploadFile {
  name: string;
  mimeType: string;
  buffer: Buffer;
}

/** A real .xlsx import sheet (template header row) built by the ops_import_sheet fixture. */
export async function importSheet(kind: "patients" | "items" | "prices", rows: unknown[][]): Promise<UploadFile> {
  const made = await fixture<{ filename: string; base64: string }>("ops_import_sheet", { kind, rows });
  return {
    name: made.filename,
    mimeType: XLSX,
    buffer: Buffer.from(made.base64, "base64"),
  };
}

/** Columns of the item template, in order (backend domain/item_import.py COLUMNS). */
const ITEM_COLUMNS = [
  "service_code",
  "name_ar",
  "name_en",
  "kind",
  "generic_name",
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
  "batch_no",
  "expiry_date",
  "quantity",
  "unit_cost",
  "store",
] as const;

export type ItemCells = Partial<Record<(typeof ITEM_COLUMNS)[number], string | number>>;

/** One item sheet row from named cells (missing cells are empty). */
export function itemRow(cells: ItemCells): (string | number)[] {
  return ITEM_COLUMNS.map((key) => cells[key] ?? "");
}

/** A tag unique to this run (upper-case letters and digits), for names, codes and phones. */
export function runTag(): string {
  return `${Date.now().toString(36)}${Math.floor(Math.random() * 46_656).toString(36)}`.toUpperCase();
}

/** Eight digits unique enough for a test phone number. */
export function phoneDigits(): string {
  return `${String(Date.now()).slice(-6)}${String(Math.floor(Math.random() * 90) + 10)}`;
}
