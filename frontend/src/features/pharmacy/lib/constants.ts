import type { DosageForm, MoveKind, StorageCode } from "../types";

/** Dosage forms in the order the item form offers them (labels in `pharmacy:forms`). */
export const DOSAGE_FORMS = [
  "tablet",
  "capsule",
  "syrup",
  "suspension",
  "injection",
  "infusion",
  "cream",
  "drops",
  "inhaler",
  "suppository",
  "sachet",
  "supply",
  "other",
] as const satisfies readonly DosageForm[];

export const STORAGE_CODES = ["room", "cool", "fridge", "frozen"] as const satisfies readonly StorageCode[];

export const MOVE_KINDS = [
  "receipt",
  "dispense",
  "adjustment",
  "transfer_out",
  "transfer_in",
  "count_correction",
  "return",
] as const satisfies readonly MoveKind[];

/** Expiry report windows (FEATURES 8.8). */
export const EXPIRY_WINDOWS = [30, 60, 90] as const;

/** What happens to the undispensed rest of a line (FLOW 6). */
export const REMAINDERS = ["defer", "refund"] as const;

/** Who a walk-in sale is billed to. */
export const SALE_MODES = ["new", "existing"] as const;
