import {
  BookOpen,
  Building2,
  FileSpreadsheet,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Tags,
  UserCog,
  type LucideIcon,
} from "lucide-react";

import type { AppPath, NavLabelKey } from "@/app/nav-types";

export type AdminSectionId =
  "users" | "roles" | "catalog" | "priceLists" | "payers" | "settings" | "imports" | "system";

export interface AdminSection {
  id: AdminSectionId;
  /** Full path of the section page. */
  to: AppPath;
  icon: LucideIcon;
  permission: string;
  navKey: NavLabelKey;
}

/**
 * Administration sub-modules. Permission codes: core.* and ops.* exist in
 * the backend registry today; catalog.* and imports.* are registered by
 * their apps in later phases.
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
    id: "settings",
    to: "/administration/settings",
    icon: SlidersHorizontal,
    permission: "core.manage_settings",
    navKey: "adminSettings",
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

export const ADMIN_PERMISSIONS: readonly string[] = ADMIN_SECTIONS.map((s) => s.permission);
