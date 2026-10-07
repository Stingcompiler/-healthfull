/**
 * Every SPA route, for the responsive matrix (responsive.spec.ts) and any spec
 * that walks the app. When a feature adds a route, add it here: the
 * "route registry" test in responsive.spec.ts fails until you do.
 *
 * `name` is the screenshot prefix: artifacts/screens/<name>-<viewport>-<theme>-<lang>.png
 */
import type { Locator, Page } from "@playwright/test";

export interface AppRoute {
  name: string;
  path: string;
  /** Needs a logged-in session (the e2e admin, who holds every permission). */
  auth: boolean;
  /** Element whose visibility proves the page finished rendering. */
  ready: (page: Page) => Locator;
}

const pageHeading = (page: Page) => page.locator("#main h1").first();
const loginSubmit = (page: Page) => page.locator('main form button[type="submit"]');

function appRoute(name: string, path: string): AppRoute {
  return { name, path, auth: true, ready: pageHeading };
}

export const ROUTES: readonly AppRoute[] = [
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

export function routeByName(name: string): AppRoute {
  const route = ROUTES.find((r) => r.name === name);
  if (!route) throw new Error(`Unknown route "${name}" (e2e/routes.ts)`);
  return route;
}
