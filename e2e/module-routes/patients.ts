/**
 * Patients screens for the responsive matrix, besides /patients (listed in e2e/routes.ts).
 * Owned by the patients module: add one entry per new screen. A path with parameters gets
 * `resolve`, which builds the data (factories from ../helpers) and returns the path to open.
 * Example:
 *
 *   appRoute("patient-file", "/patients/$patientId", {
 *     resolve: async () => `/patients/${String((await createPatient()).patient.id)}`,
 *   }),
 */
import type { AppRoute } from "../route-kit";

export const routes: readonly AppRoute[] = [];
