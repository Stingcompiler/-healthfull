import {
  BookOpen,
  Building2,
  FileSpreadsheet,
  Hospital,
  ListChecks,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Stethoscope,
  Tags,
  UserCog,
  type LucideIcon,
} from "lucide-react";

import type { AppPath, NavLabelKey } from "@/app/nav-types";

export type AdminSectionId =
  | "users"
  | "roles"
  | "settings"
  | "policies"
  | "departments"
  | "reasonCodes"
  | "catalog"
  | "priceLists"
  | "payers"
  | "imports"
  | "system";

export interface AdminSection {
  id: AdminSectionId;
  /** Full path of the section page. */
  to: AppPath;
  icon: LucideIcon;
  permission: string;
  navKey: NavLabelKey;
}

/**
 * Administration sub-modules, in sub-navigation order. Each permission code is
 * registered by the backend (core.*, catalog.*, imports.*, ops.*) and is the one
 * the section's endpoints require, so a hidden section is also a refused one.
 */
export const ADMIN_SECTIONS: readonly AdminSection[] = [
  { id: "users", to: "/administration/users", icon: UserCog, permission: "core.manage_users", navKey: "adminUsers" },
  {
    id: "roles",
    to: "/administration/roles",
    icon: ShieldCheck,
    permission: "core.manage_roles",
    navKey: "adminRoles",
  },
  {
    id: "settings",
    to: "/administration/settings",
    icon: Hospital,
    permission: "core.manage_settings",
    navKey: "adminSettings",
  },
  {
    id: "policies",
    to: "/administration/policies",
    icon: SlidersHorizontal,
    permission: "core.manage_settings",
    navKey: "adminPolicies",
  },
  {
    id: "departments",
    to: "/administration/departments",
    icon: Stethoscope,
    permission: "core.manage_departments",
    navKey: "adminDepartments",
  },
  {
    id: "reasonCodes",
    to: "/administration/reason-codes",
    icon: ListChecks,
    permission: "core.manage_reason_codes",
    navKey: "adminReasonCodes",
  },
  {
    id: "catalog",
    to: "/administration/catalog",
    icon: BookOpen,
    permission: "catalog.manage",
    navKey: "adminCatalog",
  },
  {
    id: "priceLists",
    to: "/administration/price-lists",
    icon: Tags,
    permission: "catalog.manage_prices",
    navKey: "adminPriceLists",
  },
  {
    id: "payers",
    to: "/administration/payers",
    icon: Building2,
    permission: "catalog.manage_payers",
    navKey: "adminPayers",
  },
  {
    id: "imports",
    to: "/administration/imports",
    icon: FileSpreadsheet,
    permission: "imports.run",
    navKey: "adminImports",
  },
  { id: "system", to: "/administration/system", icon: Server, permission: "ops.view_status", navKey: "adminSystem" },
];

export const ADMIN_PERMISSIONS: readonly string[] = [...new Set(ADMIN_SECTIONS.map((s) => s.permission))];

export function adminSection(id: AdminSectionId): AdminSection {
  const found = ADMIN_SECTIONS.find((s) => s.id === id);
  if (!found) throw new Error(`Unknown admin section ${id}`);
  return found;
}
