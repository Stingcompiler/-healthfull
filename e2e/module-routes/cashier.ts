/**
 * Cashier, billing and shifts screens for the responsive matrix, besides /cashier (listed in
 * e2e/routes.ts).
 * Owned by the cashier module: add one entry per new screen. A path with parameters gets
 * `resolve`, which builds the data (factories from ../helpers) and returns the path to open.
 * Example:
 *
 *   appRoute("cashier-shift", "/cashier/shift"),
 */
import type { AppRoute } from "../route-kit";

export const routes: readonly AppRoute[] = [];
