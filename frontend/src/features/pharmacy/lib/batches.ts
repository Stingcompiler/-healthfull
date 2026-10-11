/**
 * Which batches a pharmacist may take units from by hand (batch override, FEATURES 8.3).
 *
 * The server never dispenses an expired batch, override or not (`domain.stock.choose_batches`
 * answers `BATCH_EXPIRED`; `expired` on a batch row is that same rule, `is_usable`), so the
 * dialog never offers one: an expired batch is listed for information only.
 */
import { parseWhole } from "./qty";

export interface BatchChoice {
  batch_id: number;
  expired: boolean;
}

/** A batch the override may take from: never an expired one. */
export function isPickable(batch: Pick<BatchChoice, "expired">): boolean {
  return !batch.expired;
}

/** Whether the line has any batch the override could choose. */
export function hasPickable(batches: readonly BatchChoice[]): boolean {
  return batches.some(isPickable);
}

/**
 * The override picks to send: whole positive quantities of pickable batches only. A pick left
 * over for a batch that is not pickable (expired since the dialog opened) is dropped, never sent.
 */
export function overridePicks(
  batches: readonly BatchChoice[],
  picks: Readonly<Record<string, string>>,
): { batch_id: number; quantity: number }[] {
  return batches
    .filter(isPickable)
    .map((b) => ({ batch_id: b.batch_id, quantity: parseWhole(picks[String(b.batch_id)] ?? "", 0) ?? 0 }))
    .filter((p) => p.quantity > 0);
}

/**
 * Total units picked from pickable batches (an empty entry counts as none), or NaN when a
 * pickable entry is not a whole number.
 */
export function pickedTotal(batches: readonly BatchChoice[], picks: Readonly<Record<string, string>>): number {
  let total = 0;
  for (const b of batches.filter(isPickable)) {
    const raw = (picks[String(b.batch_id)] ?? "").trim();
    if (raw === "") continue;
    const qty = parseWhole(raw, 0);
    if (qty === null) return Number.NaN;
    total += qty;
  }
  return total;
}
