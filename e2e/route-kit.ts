/**
 * Shapes and helpers of the e2e route registry (routes.ts and module-routes/<module>.ts).
 * Kept apart from routes.ts so module route files never import routes.ts, which loads them.
 */
import type { Locator, Page } from "@playwright/test";

export interface AppRoute {
  /** Screenshot prefix: artifacts/screens/<name>-<viewport>-<theme>-<lang>.png. Unique. */
  name: string;
  /**
   * The path as the frontend declares it. A pattern with parameters ("/patients/$patientId")
   * also needs `resolve`.
   */
  path: string;
  /** Needs a logged-in session (the e2e admin, who holds every permission). */
  auth: boolean;
  /** Element whose visibility proves the page finished rendering. */
  ready: (page: Page) => Locator;
  /**
   * Builds the data the screen shows (factories from helpers/api.ts) and returns the concrete
   * path to visit, e.g. `/patients/412`. Called once per route per worker.
   */
  resolve?: () => Promise<string>;
}

export const pageHeading = (page: Page): Locator => page.locator("#main h1").first();
export const loginSubmit = (page: Page): Locator => page.locator('main form button[type="submit"]');

/** A logged-in screen whose page heading proves it rendered. */
export function appRoute(
  name: string,
  path: string,
  options: { ready?: AppRoute["ready"]; resolve?: AppRoute["resolve"]; auth?: boolean } = {},
): AppRoute {
  const route: AppRoute = { name, path, auth: options.auth ?? true, ready: options.ready ?? pageHeading };
  if (options.resolve) route.resolve = options.resolve;
  return route;
}

const resolved = new Map<string, Promise<string>>();

/** The path to open for `route`: its `resolve()` result (cached per worker) or its path. */
export function visitPath(route: AppRoute): Promise<string> {
  if (!route.resolve) return Promise.resolve(route.path);
  let target = resolved.get(route.name);
  if (!target) {
    target = route.resolve();
    resolved.set(route.name, target);
    target.catch(() => resolved.delete(route.name));
  }
  return target;
}
