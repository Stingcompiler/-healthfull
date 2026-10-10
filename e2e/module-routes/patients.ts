/**
 * Patients screens for the responsive matrix, besides /patients (listed in e2e/routes.ts).
 * Owned by the patients module: one entry per screen.
 */
import type { Locator, Page } from "@playwright/test";

import { apiAs, createPatient, paidVisit } from "../helpers/api";
import { appRoute, type AppRoute } from "../route-kit";

/** `inner` once the main area has no loading placeholders left (screenshots show real data). */
export function loaded(page: Page, inner: string): Locator {
  return page.locator(`#main:not(:has([data-slot="skeleton"])):not(:has([aria-busy="true"])) ${inner}`).first();
}

/** A file with what the screen can show: coverage, a paid visit, a balance and a merge. */
async function richPatientFile(): Promise<string> {
  const name = "سارة عبد الرحمن الأمين";
  const { patient } = await createPatient({ payer: "AMAN", full_name_ar: name, full_name_en: "Sara Abdelrahman" });
  await paidVisit({ patient: patient.id, doctor: "doctor" });
  const { patient: duplicate } = await createPatient({ full_name_ar: name });
  const manager = await apiAs("manager");
  await manager.call("patients_merge_patient", {
    path: { patient_id: patient.id },
    body: { duplicate_id: duplicate.id, reason_code: "DUPLICATE_REGISTRATION", note: "e2e: registered twice" },
  });
  return `/patients/${String(patient.id)}`;
}

export const routes: readonly AppRoute[] = [
  appRoute("patient-new", "/patients/new"),
  appRoute("patient-import", "/patients/import", { ready: (page) => loaded(page, "h1") }),
  appRoute("patient-file", "/patients/$patientId", {
    resolve: richPatientFile,
    ready: (page) => loaded(page, '[data-testid="merge-history"]'),
  }),
  appRoute("patient-portal-code", "/patients/$patientId/portal-code", {
    // A file with a phone (the factory generates one): reception may issue a portal code.
    resolve: async () => `/patients/${String((await createPatient()).patient.id)}/portal-code`,
    ready: (page) => loaded(page, '[data-testid="portal-code-issue"]'),
  }),
];
