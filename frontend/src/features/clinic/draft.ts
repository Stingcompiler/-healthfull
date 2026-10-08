/**
 * The order being written, before it is placed: form state only. Quantities of prescriptions
 * are computed by the server (prescription preview and again when the order is placed).
 */
import { pickName } from "@/lib/names";
import type { Language } from "@/lib/preferences";

import type { OrderableKind, OrderableService, OrderItemInput, OrderSet, OrderSetInput, Route } from "./types";

export interface DraftRx {
  /** Dose as written ("1 tablet", "500 mg"); built from the dose quantity when left empty. */
  dose: string;
  doseQuantity: string;
  frequencyCode: string;
  durationDays: string;
  route: Route;
  asNeeded: boolean;
  instructions: string;
}

export interface DraftItem {
  key: string;
  serviceId: number;
  code: string;
  kind: OrderableKind;
  nameAr: string;
  nameEn: string;
  /** Base unit of a drug (tablet, ml...), for labels only. */
  unitAr: string;
  unitEn: string;
  /** Lab, procedure, consumable: units ordered. Drug: an explicit quantity (blank = computed). */
  quantity: string;
  /** The quantity the server computed for the prescription (display and favorites only). */
  computedQuantity: number | null;
  note: string;
  rx: DraftRx | null;
}

let counter = 0;
const nextKey = () => {
  counter += 1;
  return `d${String(counter)}`;
};

const EMPTY_RX: DraftRx = {
  dose: "",
  doseQuantity: "1",
  frequencyCode: "",
  durationDays: "",
  route: "oral",
  asNeeded: false,
  instructions: "",
};

export function draftFromService(service: OrderableService): DraftItem {
  const drug = service.kind === "drug";
  return {
    key: nextKey(),
    serviceId: service.id,
    code: service.code,
    kind: service.kind,
    nameAr: service.name_ar,
    nameEn: service.name_en,
    unitAr: service.drug?.base_unit_name_ar ?? "",
    unitEn: service.drug?.base_unit_name_en ?? "",
    quantity: drug ? "" : "1",
    computedQuantity: null,
    note: "",
    rx: drug ? { ...EMPTY_RX } : null,
  };
}

export function draftsFromOrderSet(set: OrderSet): DraftItem[] {
  return set.items
    .filter((it): it is typeof it & { kind: OrderableKind } =>
      ["lab", "procedure", "drug", "consumable"].includes(it.kind),
    )
    .map((it) => ({
      key: nextKey(),
      serviceId: it.service_id,
      code: it.service_code,
      kind: it.kind,
      nameAr: it.name_ar,
      nameEn: it.name_en,
      unitAr: "",
      unitEn: "",
      quantity: it.quantity,
      computedQuantity: null,
      note: it.kind === "drug" ? "" : it.instructions,
      rx:
        it.kind === "drug"
          ? {
              ...EMPTY_RX,
              dose: it.dose,
              doseQuantity: "",
              frequencyCode: it.frequency_code,
              durationDays: it.duration_days ? String(it.duration_days) : "",
              instructions: it.instructions,
            }
          : null,
    }));
}

function doseText(item: DraftItem, language: Language): string {
  const rx = item.rx;
  if (!rx) return "";
  if (rx.dose.trim()) return rx.dose.trim();
  const unit = pickName({ ar: item.unitAr, en: item.unitEn }, language);
  return [rx.doseQuantity.trim(), unit].filter(Boolean).join(" ");
}

const positiveInt = (value: string): number | null => {
  const n = Number(value.trim());
  return value.trim() !== "" && Number.isInteger(n) && n > 0 ? n : null;
};

/** The request body of one draft item (the server validates and computes the rest). */
export function toOrderItem(item: DraftItem, language: Language): OrderItemInput {
  const quantity = positiveInt(item.quantity);
  if (!item.rx) {
    return { service_id: item.serviceId, quantity: quantity ?? 1, note: item.note.trim(), pre_approval_ref: "" };
  }
  const rx = item.rx;
  return {
    service_id: item.serviceId,
    quantity,
    note: item.note.trim(),
    pre_approval_ref: "",
    prescription: {
      dose: doseText(item, language).slice(0, 60),
      dose_quantity: rx.doseQuantity.trim() || null,
      route: rx.route,
      frequency_code: rx.frequencyCode,
      duration_days: positiveInt(rx.durationDays),
      as_needed: rx.asNeeded,
      instructions: rx.instructions.trim(),
    },
  };
}

/** The draft saved as one of the doctor's favorites. */
export function toFavorite(name: string, items: readonly DraftItem[], language: Language): OrderSetInput {
  return {
    name_ar: language === "ar" ? name : "",
    name_en: language === "en" ? name : "",
    items: items.map((item) => ({
      service_id: item.serviceId,
      quantity: positiveInt(item.quantity) ?? item.computedQuantity ?? 1,
      dose: item.rx ? doseText(item, language).slice(0, 60) : "",
      frequency_code: item.rx?.frequencyCode ?? "",
      duration_days: item.rx ? positiveInt(item.rx.durationDays) : null,
      instructions: (item.rx ? item.rx.instructions : item.note).trim().slice(0, 300),
    })),
  };
}
