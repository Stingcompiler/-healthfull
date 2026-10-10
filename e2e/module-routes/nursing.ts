/**
 * Nursing screens for the responsive matrix, besides /nursing (listed in e2e/routes.ts).
 * Owned by the nursing module. Each `ready` waits for loaded content, never for the page
 * heading alone (it renders before the data). The procedure desk is also checked with a paid
 * procedure in it (`nursing-desk`), and the chart on a paid visit with vitals and a note.
 */
import type { Page } from "@playwright/test";

import { apiAs, approveInvoice, orderLines, paidVisit, pay, type PaidVisitResult } from "../helpers";
import { appRoute, type AppRoute } from "../route-kit";

let visit: Promise<PaidVisitResult> | undefined;

/** A paid visit with a paid injection waiting, vitals and a nursing note (once per worker). */
function nursedVisit(): Promise<PaidVisitResult> {
  visit ??= (async () => {
    const ready = await paidVisit({
      patient_fields: { allergies: ["PENICILLIN"], full_name_en: "Khadija Babiker Elnour Ali" },
    });
    await orderLines({ visit: ready.visit, items: [{ service: "PRC-INJ", note: "IM ceftriaxone 1 g" }] });
    const { invoice } = await approveInvoice({ visit: ready.visit, services: ["PRC-INJ"] });
    await pay({ invoice });
    const nurse = await apiAs("nurse");
    await nurse.post(`/api/clinical/visits/${String(ready.visit.id)}/vitals`, {
      temperature_c: "38.4",
      bp_systolic: 118,
      bp_diastolic: 76,
      pulse_bpm: 102,
      spo2_percent: 97,
    });
    await nurse.post(`/api/clinical/nursing/visits/${String(ready.visit.id)}/notes`, {
      text: "Febrile, alert. Oral fluids encouraged.",
    });
    return ready;
  })();
  return visit;
}

const procedureCard = (page: Page) => page.getByTestId("procedure-card").first();
const visitRow = (page: Page) => page.getByTestId("nursing-visit").first();
const vitalsList = (page: Page) => page.getByTestId("vitals-list");
const bedCard = (page: Page) => page.getByTestId("bed-card").first();

export const routes: readonly AppRoute[] = [
  appRoute("nursing-desk", "/nursing", {
    ready: procedureCard,
    resolve: async () => {
      await nursedVisit();
      return "/nursing";
    },
  }),
  appRoute("nursing-visits", "/nursing/visits", {
    ready: visitRow,
    resolve: async () => {
      await nursedVisit();
      return "/nursing/visits";
    },
  }),
  appRoute("nursing-chart", "/nursing/visits/$visitId", {
    ready: vitalsList,
    resolve: async () => `/nursing/visits/${String((await nursedVisit()).visit.id)}`,
  }),
  appRoute("nursing-beds", "/nursing/beds", { ready: bedCard }),
];
