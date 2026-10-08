/**
 * Visits, queue and appointments screens for the responsive matrix, besides /queue and
 * /appointments (listed in e2e/routes.ts). Owned by the visits module.
 */
import { appRoute, type AppRoute } from "../route-kit";

export const routes: readonly AppRoute[] = [appRoute("queue-display", "/queue/display")];
