/**
 * Clinic (doctor) screens for the responsive matrix, besides /clinic (listed in e2e/routes.ts).
 * Owned by the clinic module: one entry per screen. The workspace is opened on a paid visit
 * of a patient with a penicillin allergy and a few orders, so the summary, allergy chips and
 * order cards all render.
 */
import { orderLines, paidVisit } from "../helpers";
import { appRoute, type AppRoute } from "../route-kit";

export const routes: readonly AppRoute[] = [
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
