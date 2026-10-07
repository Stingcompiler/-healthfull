/*
 * Navigation registry. Every feature module contributes its entries from
 * features/<module>/nav.ts; they are all imported here once, so new feature
 * work adds entries in its own folder and never edits this file.
 */
import { nav as admin } from "@/features/admin/nav";
import { nav as cashier } from "@/features/cashier/nav";
import { nav as claims } from "@/features/claims/nav";
import { nav as clinic } from "@/features/clinic/nav";
import { nav as dashboard } from "@/features/dashboard/nav";
import { nav as design } from "@/features/design/nav";
import { nav as lab } from "@/features/lab/nav";
import { nav as nursing } from "@/features/nursing/nav";
import { nav as patients } from "@/features/patients/nav";
import { nav as pharmacy } from "@/features/pharmacy/nav";
import { nav as reports } from "@/features/reports/nav";
import { nav as visits } from "@/features/visits/nav";
import type { MeOut } from "@/lib/api/contract";
import { hasPermission } from "@/lib/auth/permissions";

import type { NavItem } from "./nav-types";

export const ALL_NAV: readonly NavItem[] = [
  ...dashboard,
  ...patients,
  ...visits,
  ...clinic,
  ...cashier,
  ...claims,
  ...pharmacy,
  ...lab,
  ...nursing,
  ...reports,
  ...admin,
  ...design,
].sort((a, b) => a.order - b.order);

/** Entries the user may see: any listed permission grants the item. */
export function visibleNav(me: Pick<MeOut, "roles" | "permissions"> | null): NavItem[] {
  return ALL_NAV.filter((item) => hasPermission(me, item.permission, "any"));
}
