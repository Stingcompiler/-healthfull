/**
 * Patients screens for the responsive matrix, besides /patients (listed in e2e/routes.ts).
 * Owned by the patients module: one entry per screen.
 */
import { createPatient } from "../helpers/api";
import { appRoute, type AppRoute } from "../route-kit";

export const routes: readonly AppRoute[] = [
  appRoute("patient-new", "/patients/new"),
  appRoute("patient-file", "/patients/$patientId", {
    resolve: async () => `/patients/${String((await createPatient({ payer: "AMAN" })).patient.id)}`,
  }),
];
