/**
 * System pages of the administration for the responsive matrix: data export and the audit
 * trail (/administration/imports and /administration/system are listed in e2e/routes.ts).
 * Owned by the ops module.
 */
import { appRoute, type AppRoute } from "../route-kit";

export const routes: readonly AppRoute[] = [
  appRoute("admin-export", "/administration/export"),
  appRoute("admin-audit", "/administration/audit"),
];
