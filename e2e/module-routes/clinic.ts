/**
 * Clinic (doctor) screens for the responsive matrix, besides /clinic (listed in e2e/routes.ts).
 * Owned by the clinic module: add one entry per new screen. A path with parameters gets
 * `resolve`, which builds the data (factories from ../helpers) and returns the path to open.
 * Example:
 *
 *   appRoute("clinic-visit", "/clinic/visits/$visitId", {
 *     resolve: async () => `/clinic/visits/${String((await paidVisit()).visit.id)}`,
 *   }),
 */
import type { AppRoute } from "../route-kit";

export const routes: readonly AppRoute[] = [];
