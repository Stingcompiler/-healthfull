/**
 * The report catalog as the screens show it: each report's key, area, icon and the one
 * permission its endpoints require. Mirrors backend/apps/reports/registry.py; catalog.test.ts
 * reads that file and fails on any difference, so a report cannot be listed under the wrong
 * code or forgotten here. Hiding by permission is presentation only: the server refuses.
 */
import {
  AlarmClock,
  Banknote,
  CalendarClock,
  ClipboardList,
  FlaskConical,
  HandCoins,
  Hourglass,
  Landmark,
  type LucideIcon,
  Package,
  PackageSearch,
  ReceiptText,
  Scale,
  ShieldCheck,
  Users,
  Wallet,
} from "lucide-react";

export const REPORT_AREAS = ["finance", "exceptions", "payers", "stock", "visits", "lab"] as const;
export type ReportAreaKey = (typeof REPORT_AREAS)[number];

export interface CatalogEntry {
  key: string;
  area: ReportAreaKey;
  permission: string;
  icon: LucideIcon;
}

export const REPORT_CATALOG = [
  { key: "revenue", area: "finance", permission: "reports.view_finance", icon: Banknote },
  { key: "shift_variances", area: "finance", permission: "reports.view_finance", icon: Scale },
  { key: "pending_transfers", area: "finance", permission: "reports.view_finance", icon: Hourglass },
  { key: "adjustments", area: "finance", permission: "reports.view_finance", icon: ReceiptText },
  { key: "payer_receivables", area: "payers", permission: "reports.view_finance", icon: Landmark },
  { key: "requested_not_invoiced", area: "exceptions", permission: "reports.view_exceptions", icon: ClipboardList },
  { key: "paid_not_performed", area: "exceptions", permission: "reports.view_exceptions", icon: Wallet },
  {
    key: "performed_by_authorization",
    area: "exceptions",
    permission: "reports.view_exceptions",
    icon: ShieldCheck,
  },
  { key: "stock_valuation", area: "stock", permission: "reports.view_stock", icon: HandCoins },
  { key: "stock_movement", area: "stock", permission: "reports.view_stock", icon: Package },
  { key: "stock_variance", area: "stock", permission: "reports.view_stock", icon: PackageSearch },
  { key: "stock_expiry", area: "stock", permission: "reports.view_stock", icon: CalendarClock },
  { key: "visits", area: "visits", permission: "reports.view_visits", icon: Users },
  { key: "lab_turnaround", area: "lab", permission: "reports.view_lab", icon: FlaskConical },
] as const satisfies readonly CatalogEntry[];

export type ReportKey = (typeof REPORT_CATALOG)[number]["key"];

/** Every code that opens at least one report (the nav entry shows for any of them). */
export const REPORT_PERMISSIONS: readonly string[] = [...new Set(REPORT_CATALOG.map((r) => r.permission))];

export const DASHBOARD_PERMISSION = "reports.view_dashboard";

/** The icon of an area heading. */
export const AREA_ICONS: Record<ReportAreaKey, LucideIcon> = {
  finance: Banknote,
  exceptions: AlarmClock,
  payers: Landmark,
  stock: Package,
  visits: Users,
  lab: FlaskConical,
};

export function catalogEntry(key: string): (typeof REPORT_CATALOG)[number] | undefined {
  return REPORT_CATALOG.find((r) => r.key === key);
}

export function isReportKey(key: string): key is ReportKey {
  return catalogEntry(key) !== undefined;
}
