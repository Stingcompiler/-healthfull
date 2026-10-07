/**
 * Visits, queue and appointments screens for the responsive matrix, besides /queue and
 * /appointments (listed in e2e/routes.ts).
 * Owned by the visits module: add one entry per new screen. A path with parameters gets
 * `resolve`, which builds the data (factories from ../helpers) and returns the path to open.
 * Example:
 *
 *   appRoute("visit-detail", "/visits/$visitId", {
 *     resolve: async () => {
 *       const { patient } = await createPatient();
 *       return `/visits/${String((await createVisit({ patient })).visit.id)}`;
 *     },
 *   }),
 */
import type { AppRoute } from "../route-kit";

export const routes: readonly AppRoute[] = [];
