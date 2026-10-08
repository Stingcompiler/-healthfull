import { FlaskConical, Package, Pill, Syringe, type LucideIcon } from "lucide-react";

import type { OrderableKind } from "./types";

/** The icon of each kind of orderable service (shown with its text, never alone). */
export const KIND_ICONS: Record<OrderableKind, LucideIcon> = {
  lab: FlaskConical,
  procedure: Syringe,
  drug: Pill,
  consumable: Package,
};
