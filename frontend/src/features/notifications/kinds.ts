/**
 * What each notification kind says and where it leads (FEATURES 0.13). The server sends a
 * kind and a payload of ids, numbers and amounts; the text is translated here
 * (`ops:notifications.kinds.<kind>`) and the link opens the screen that resolves it.
 */
import { formatMoney, formatNumber } from "@/lib/format";
import type { Language } from "@/lib/preferences";

import type { AppNotification } from "./api";

export const KNOWN_KINDS = [
  "lab_result_ready",
  "lab_result_critical",
  "stock_low",
  "stock_low_summary",
  "transfers_pending_overdue",
  "transfer_rejected",
  "patient_credit_negative",
  "shift_variance",
  "shift_review_pending",
  "backup_stale",
] as const;

export type KnownKind = (typeof KNOWN_KINDS)[number];

export type NotificationTarget =
  | { to: "/clinic/visits/$visitId"; visitId: string }
  | { to: "/patients/$patientId"; patientId: string }
  | { to: "/pharmacy/low-stock" }
  | { to: "/cashier/transfers" }
  | { to: "/cashier/review" }
  | { to: "/administration/system" };

export function isKnownKind(kind: string): kind is KnownKind {
  return (KNOWN_KINDS as readonly string[]).includes(kind);
}

function str(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}
const num = (value: unknown): number => (typeof value === "number" ? value : Number(value ?? 0) || 0);

/** Interpolation values of a notification's text, formatted for `language`. */
export function notificationParams(note: AppNotification, language: Language): Record<string, string | number> {
  const p = note.payload;
  const critical = Array.isArray(p.critical) ? p.critical.map(str).join(", ") : "";
  return {
    count: num(p.count),
    days: formatNumber(num(p.days), language),
    hours: formatNumber(num(p.hours), language),
    onHand: formatNumber(num(p.on_hand), language),
    min: formatNumber(num(p.min_stock), language),
    number: str(p.payment_number ?? p.shift_number ?? p.number),
    amount: p.amount != null ? formatMoney(str(p.amount), language) : "",
    variance: p.variance != null ? formatMoney(str(p.variance), language, { signed: true }) : "",
    critical,
  };
}

/** The screen a notification opens, or null when there is nothing to open. */
export function notificationTarget(note: AppNotification): NotificationTarget | null {
  const p = note.payload;
  switch (note.kind) {
    case "lab_result_ready":
    case "lab_result_critical":
      return p.visit_id != null ? { to: "/clinic/visits/$visitId", visitId: str(p.visit_id) } : null;
    case "stock_low":
    case "stock_low_summary":
      return { to: "/pharmacy/low-stock" };
    case "transfers_pending_overdue":
    case "transfer_rejected":
      return { to: "/cashier/transfers" };
    case "patient_credit_negative":
      return p.patient_id != null ? { to: "/patients/$patientId", patientId: str(p.patient_id) } : null;
    case "shift_variance":
    case "shift_review_pending":
      return { to: "/cashier/review" };
    case "backup_stale":
      return { to: "/administration/system" };
    default:
      return null;
  }
}

/** Kinds that need attention now (shown with the danger tone). */
export function isUrgent(kind: string): boolean {
  return kind === "lab_result_critical" || kind === "transfer_rejected" || kind === "patient_credit_negative";
}
