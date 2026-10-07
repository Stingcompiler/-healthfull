import { createRoute, Outlet, type AnyRoute } from "@tanstack/react-router";

import { AdminIndexPage } from "./pages/AdminIndexPage";
import { AdminSectionPage } from "./pages/AdminSectionPage";
import type { AdminSectionId } from "./sections";

function section(id: AdminSectionId) {
  return function AdminSectionRoute() {
    return <AdminSectionPage id={id} />;
  };
}

/**
 * Mounted at /administration, not /admin: /admin/* belongs to the Django
 * admin (the dev proxy and the production reverse proxy send it to the
 * backend), so SPA deep links there would never reach the frontend.
 */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const admin = createRoute({
    getParentRoute: () => parent,
    path: "/administration",
    component: Outlet,
  });
  const index = createRoute({ getParentRoute: () => admin, path: "/", component: AdminIndexPage });
  const users = createRoute({ getParentRoute: () => admin, path: "/users", component: section("users") });
  const roles = createRoute({ getParentRoute: () => admin, path: "/roles", component: section("roles") });
  const catalog = createRoute({ getParentRoute: () => admin, path: "/catalog", component: section("catalog") });
  const priceLists = createRoute({
    getParentRoute: () => admin,
    path: "/price-lists",
    component: section("priceLists"),
  });
  const payers = createRoute({ getParentRoute: () => admin, path: "/payers", component: section("payers") });
  const settings = createRoute({ getParentRoute: () => admin, path: "/settings", component: section("settings") });
  const imports = createRoute({ getParentRoute: () => admin, path: "/imports", component: section("imports") });
  const system = createRoute({ getParentRoute: () => admin, path: "/system", component: section("system") });
  return [admin.addChildren([index, users, roles, catalog, priceLists, payers, settings, imports, system])] as const;
}
