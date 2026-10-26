/**
 * Clinic (doctor) screens for the responsive matrix, besides /clinic (listed in e2e/routes.ts).
 * Owned by the clinic module: one entry per screen. The workspace is opened on a paid visit
 * of a patient with a penicillin allergy and a few orders, so the summary, allergy chips and
 * order cards all render.
 */
import { apiAs, orderLines, paidVisit } from "../helpers";
import { appRoute, type AppRoute } from "../route-kit";

interface PrintedVisit {
  visitId: number;
  referralId: number;
}

let printed: Promise<PrintedVisit> | undefined;

/** One paid visit with a prescription and an outside referral, built once per worker (F03). */
function printedOnce(): Promise<PrintedVisit> {
  printed ??= (async () => {
    const { visit } = await paidVisit({
      patient_fields: { allergies: ["PENICILLIN"], full_name_en: "Hawa Abdelrahim Musa Adam" },
    });
    await orderLines({
      visit,
      items: [
        {
          service: "DRG-PARA500",
          prescription: { dose: "1 tablet", dose_quantity: "1", frequency_code: "TID", duration_days: 5 },
        },
      ],
    });
    const doctor = await apiAs("doctor");
    const referral = await doctor.post<{ id: number }>(`/api/clinical/visits/${String(visit.id)}/referrals`, {
      kind: "external",
      external_facility: "Khartoum Teaching Hospital",
      reason: "Suspected appendicitis, surgical opinion",
      clinical_summary: "Right lower quadrant pain for two days, fever 38.4",
      urgency: "urgent",
    });
    return { visitId: visit.id, referralId: referral.id };
  })();
  return printed;
}

export const routes: readonly AppRoute[] = [
  appRoute("clinic-prescription-print", "/clinic/visits/$visitId/prescription/print", {
    resolve: async () => `/clinic/visits/${String((await printedOnce()).visitId)}/prescription/print`,
    ready: (page) => page.getByTestId("prescription-print"),
  }),
  appRoute("clinic-referral-print", "/clinic/referrals/$referralId/print", {
    resolve: async () => `/clinic/referrals/${String((await printedOnce()).referralId)}/print`,
    ready: (page) => page.getByTestId("referral-print"),
  }),
  appRoute("clinic-visit", "/clinic/visits/$visitId", {
    resolve: async () => {
      const { visit } = await paidVisit({
        patient_fields: { allergies: ["PENICILLIN"], full_name_en: "Amna Hassan Ali Mohamed" },
      });
      await orderLines({
        visit,
        items: [
          { service: "LAB-CBC" },
          { service: "LAB-BFMP" },
          {
            service: "DRG-PARA500",
            prescription: { dose: "1 tablet", dose_quantity: "1", frequency_code: "TID", duration_days: 5 },
          },
        ],
      });
      return `/clinic/visits/${String(visit.id)}`;
    },
  }),
];
