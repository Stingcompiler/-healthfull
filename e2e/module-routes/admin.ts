/**
 * Administration screens for the responsive matrix, besides /administration and its
 * sections (listed in e2e/routes.ts).
 * Owned by the admin module: add one entry per new screen. A path with parameters gets
 * `resolve`, which builds the data (factories from ../helpers) and returns the path to open.
 * Example:
 *
 *   appRoute("admin-departments", "/administration/departments"),
 */
import type { AppRoute } from "../route-kit";

export const routes: readonly AppRoute[] = [];
