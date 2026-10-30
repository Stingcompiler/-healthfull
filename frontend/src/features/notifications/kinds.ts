/**
 * What each notification kind says and where it leads (FEATURES 0.13). The server sends a
 * kind and a payload of ids, numbers and amounts; the text is translated here
 * (`ops:notifications.kinds.<kind>`) and the link opens the screen that resolves it.
 */
import type { MeOut } from "@/lib/api/contract";
import { hasPermission } from "@/lib/auth/permissions";
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
  "integrity_failed",
  "online_booking_requested",
  "online_booking_cancelled_by_patient",
] as const;

export type KnownKind = (typeof KNOWN_KINDS)[number];

export type NotificationTarget =
  | { to: "/clinic/visits/$visitId"; visitId: string }
  | { to: "/patients/$patientId"; patientId: string }
  | { to: "/pharmacy/low-stock" }
  | { to: "/cashier/transfers" }
  | { to: "/cashier/review" }
  | { to: "/administration/system" }
  | { to: "/appointments" };

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

export type NotificationRoute = NotificationTarget["to"];

export interface NotificationLink {
  route: NotificationRoute;
  /** The permission the screen's endpoints require. */
  permission: string;
}

/**
 * The screens that resolve each kind, in order of preference, with the permission each needs.
 * Mirrors backend/apps/core/notification_kinds.py (kinds.test.ts reads it and fails on any
 * difference), where a backend test proves every default recipient may open one of them.
 */
export const NOTIFICATION_LINKS: Readonly<Record<KnownKind, readonly NotificationLink[]>> = {
  lab_result_ready: [{ route: "/clinic/visits/$visitId", permission: "clinical.view" }],
  lab_result_critical: [{ route: "/clinic/visits/$visitId", permission: "clinical.view" }],
  stock_low: [{ route: "/pharmacy/low-stock", permission: "pharmacy.view" }],
  stock_low_summary: [{ route: "/pharmacy/low-stock", permission: "pharmacy.view" }],
  transfers_pending_overdue: [{ route: "/cashier/transfers", permission: "payments.confirm_transfer" }],
  transfer_rejected: [
    { route: "/cashier/transfers", permission: "payments.confirm_transfer" },
    { route: "/patients/$patientId", permission: "patients.view" },
  ],
  patient_credit_negative: [{ route: "/patients/$patientId", permission: "patients.view" }],
  shift_variance: [{ route: "/cashier/review", permission: "payments.review_shift" }],
  shift_review_pending: [{ route: "/cashier/review", permission: "payments.review_shift" }],
  backup_stale: [{ route: "/administration/system", permission: "ops.view_status" }],
  integrity_failed: [{ route: "/administration/system", permission: "ops.view_status" }],
  online_booking_requested: [{ route: "/appointments", permission: "visits.manage_online_bookings" }],
  online_booking_cancelled_by_patient: [{ route: "/appointments", permission: "visits.manage_online_bookings" }],
};

function targetOf(route: NotificationRoute, p: AppNotification["payload"]): NotificationTarget | null {
  switch (route) {
    case "/clinic/visits/$visitId":
      return p.visit_id != null ? { to: route, visitId: str(p.visit_id) } : null;
    case "/patients/$patientId":
      return p.patient_id != null ? { to: route, patientId: str(p.patient_id) } : null;
    default:
      return { to: route };
  }
}

/**
 * The screen a notification opens for `me`: the first of its kind's screens they may open
 * whose ids the payload carries, or null when there is none (no dead link to a refused page).
 */
export function notificationTarget(
  note: AppNotification,
  me: Pick<MeOut, "roles" | "permissions"> | null | undefined,
): NotificationTarget | null {
  if (!isKnownKind(note.kind)) return null;
  for (const link of NOTIFICATION_LINKS[note.kind]) {
    if (!hasPermission(me, link.permission)) continue;
    const target = targetOf(link.route, note.payload);
    if (target) return target;
  }
  return null;
}

/** Kinds that need attention now (shown with the danger tone). */
export function isUrgent(kind: string): boolean {
  return (
    kind === "lab_result_critical" ||
    kind === "transfer_rejected" ||
    kind === "patient_credit_negative" ||
    kind === "integrity_failed"
  );
}
