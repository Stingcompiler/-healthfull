/**
 * Report screens for the responsive matrix, besides /reports and the dashboard at / (listed in
 * e2e/routes.ts). Owned by the reports module. Each screen is checked with data in it: one
 * call to the backend fixture `reports_day` per screen builds a traceable day of activity, and
 * the screen's dates are pinned to that fixture's own day (never "today" at visit time), so a
 * run that crosses midnight still shows the rows. `ready` waits for loaded sections, not just
 * the page heading.
 */
import type { Locator, Page } from "@playwright/test";

import { fixture } from "../helpers";
import { appRoute, type AppRoute } from "../route-kit";

export interface ReportsDay {
  day: string;
  doctor: { id: number; user_id: number; username: string; name_ar: string; name_en: string };
  patient: { file_no: string };
  visit: { number: string };
  cash: { number: string; amount: string };
  transfer: { number: string; amount: string };
  expected: {
    gross: string;
    discount: string;
    net: string;
    cash: string;
    pending: string;
    paid_not_performed: Record<string, string>;
    requested_not_invoiced: string[];
  };
}

/** One traceable day of activity (a new doctor, patient and visit per call). */
export function reportsDay(): Promise<ReportsDay> {
  return fixture<ReportsDay>("reports_day", {});
}

/** The report's sections finished loading (a table row or a card with data). */
function loadedSection(page: Page, section: string): Locator {
  return page
    .getByTestId(`section-${section}`)
    .locator(
      '[data-slot="data-table"][data-mode="table"] tbody tr:not(:has([data-slot="skeleton"])):not(:has(td[colspan])), ' +
        '[data-slot="data-table-cards"] [role="listitem"]:not(:has([data-slot="skeleton"]))',
    )
    .first();
}

export const routes: readonly AppRoute[] = [
  appRoute("reports-revenue", "/reports/$reportKey", {
    resolve: async () => {
      const { day } = await reportsDay();
      return `/reports/revenue?from=${day}&to=${day}`;
    },
    ready: (page) => loadedSection(page, "by_doctor"),
  }),
  appRoute("reports-paid-not-performed", "/reports/$reportKey", {
    resolve: async () => {
      await reportsDay();
      return "/reports/paid_not_performed";
    },
    ready: (page) => loadedSection(page, "lines"),
  }),
  appRoute("reports-print", "/reports/$reportKey/print", {
    resolve: async () => {
      const { day } = await reportsDay();
      return `/reports/adjustments/print?from=${day}&to=${day}`;
    },
    ready: (page) => page.getByTestId("report-print-document"),
  }),
];
