import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { AdminLayout } from "./components/AdminLayout";
import { AdminIndexPage } from "./pages/AdminIndexPage";
import { AuditPage } from "./pages/AuditPage";
import { CatalogPage } from "./pages/CatalogPage";
import { DepartmentsPage } from "./pages/DepartmentsPage";
import { ExportPage } from "./pages/ExportPage";
import { ImportsPage } from "./pages/ImportsPage";
import { PayerPage } from "./pages/PayerPage";
import { PayersPage } from "./pages/PayersPage";
import { PoliciesPage } from "./pages/PoliciesPage";
import { PriceListPage } from "./pages/PriceListPage";
import { PriceListsPage } from "./pages/PriceListsPage";
import { ReasonCodesPage } from "./pages/ReasonCodesPage";
import { RolesPage } from "./pages/RolesPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SystemPage } from "./pages/SystemPage";
import { UsersPage } from "./pages/UsersPage";

/**
 * Mounted at /administration, not /admin: /admin/* belongs to the Django
 * admin (the dev proxy and the production reverse proxy send it to the
 * backend), so SPA deep links there would never reach the frontend (ADR 0002).
 */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const admin = createRoute({ getParentRoute: () => parent, path: "/administration", component: AdminLayout });
  const index = createRoute({ getParentRoute: () => admin, path: "/", component: AdminIndexPage });
  const users = createRoute({ getParentRoute: () => admin, path: "/users", component: UsersPage });
  const roles = createRoute({ getParentRoute: () => admin, path: "/roles", component: RolesPage });
  const settings = createRoute({ getParentRoute: () => admin, path: "/settings", component: SettingsPage });
  const policies = createRoute({ getParentRoute: () => admin, path: "/policies", component: PoliciesPage });
  const departments = createRoute({ getParentRoute: () => admin, path: "/departments", component: DepartmentsPage });
  const reasonCodes = createRoute({ getParentRoute: () => admin, path: "/reason-codes", component: ReasonCodesPage });
  const catalog = createRoute({ getParentRoute: () => admin, path: "/catalog", component: CatalogPage });
  const priceLists = createRoute({ getParentRoute: () => admin, path: "/price-lists", component: PriceListsPage });
  const priceList = createRoute({
    getParentRoute: () => admin,
    path: "/price-lists/$priceListId",
    component: PriceListPage,
  });
  const payers = createRoute({ getParentRoute: () => admin, path: "/payers", component: PayersPage });
  const payer = createRoute({ getParentRoute: () => admin, path: "/payers/$payerId", component: PayerPage });
  const imports = createRoute({ getParentRoute: () => admin, path: "/imports", component: ImportsPage });
  const system = createRoute({ getParentRoute: () => admin, path: "/system", component: SystemPage });
  const dataExport = createRoute({ getParentRoute: () => admin, path: "/export", component: ExportPage });
  const audit = createRoute({ getParentRoute: () => admin, path: "/audit", component: AuditPage });
  return [
    admin.addChildren([
      index,
      users,
      roles,
      settings,
      policies,
      departments,
      reasonCodes,
      catalog,
      priceLists,
      priceList,
      payers,
      payer,
      imports,
      system,
      dataExport,
      audit,
    ]),
  ] as const;
}
