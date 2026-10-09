/**
 * Every SPA route, for the responsive matrix (responsive.spec.ts) and any spec
 * that walks the app. The module roots are listed here; each module lists the
 * screens it adds in its own module-routes/<module>.ts (`export const routes`),
 * which is loaded automatically, so parallel module work never edits this file.
 * The "route registry" test in responsive.spec.ts fails until every route a
 * frontend routes.tsx declares is listed.
 *
 * `name` is the screenshot prefix: artifacts/screens/<name>-<viewport>-<theme>-<lang>.png
 */
import { readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { appRoute, loginSubmit, pageHeading, type AppRoute } from "./route-kit";

export { appRoute, visitPath, type AppRoute } from "./route-kit";

const CORE_ROUTES: readonly AppRoute[] = [
  // Public and auth screens (features/auth, portal, root not-found)
  { name: "login", path: "/login", auth: false, ready: loginSubmit },
  appRoute("change-password", "/change-password"),
  { name: "portal", path: "/portal", auth: false, ready: pageHeading },
  { name: "not-found", path: "/this-page-does-not-exist", auth: false, ready: pageHeading },

  // Authenticated app shell
  appRoute("dashboard", "/"),
  appRoute("patients", "/patients"),
  appRoute("queue", "/queue"),
  appRoute("appointments", "/appointments"),
  appRoute("clinic", "/clinic"),
  appRoute("cashier", "/cashier"),
  appRoute("pharmacy", "/pharmacy"),
  appRoute("lab", "/lab"),
  appRoute("nursing", "/nursing"),
  appRoute("claims", "/claims"),
  appRoute("reports", "/reports"),

  // Administration lives at /administration; /admin/* is the Django admin (ADR 0002).
  appRoute("administration", "/administration"),
  appRoute("admin-users", "/administration/users"),
  appRoute("admin-roles", "/administration/roles"),
  appRoute("admin-catalog", "/administration/catalog"),
  appRoute("admin-price-lists", "/administration/price-lists"),
  appRoute("admin-payers", "/administration/payers"),
  appRoute("admin-settings", "/administration/settings"),
  appRoute("admin-imports", "/administration/imports"),
  appRoute("admin-system", "/administration/system"),

  // Living style guide
  appRoute("design", "/design"),
];

const MODULE_ROUTES_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "module-routes");

async function moduleRoutes(): Promise<AppRoute[]> {
  const files = readdirSync(MODULE_ROUTES_DIR)
    .filter((f) => f.endsWith(".ts") && !f.endsWith(".d.ts") && !f.startsWith("_"))
    .sort();
  const found: AppRoute[] = [];
  for (const file of files) {
    const loaded = (await import(pathToFileURL(path.join(MODULE_ROUTES_DIR, file)).href)) as {
      routes?: readonly AppRoute[];
    };
    if (!loaded.routes) throw new Error(`e2e/module-routes/${file} must export "routes"`);
    found.push(...loaded.routes);
  }
  return found;
}

export const ROUTES: readonly AppRoute[] = [...CORE_ROUTES, ...(await moduleRoutes())];

const duplicates = ROUTES.map((r) => r.name).filter((name, i, all) => all.indexOf(name) !== i);
if (duplicates.length > 0) throw new Error(`Duplicate e2e route names: ${duplicates.join(", ")}`);

export function routeByName(name: string): AppRoute {
  const route = ROUTES.find((r) => r.name === name);
  if (!route) throw new Error(`Unknown route "${name}" (e2e/routes.ts)`);
  return route;
}
