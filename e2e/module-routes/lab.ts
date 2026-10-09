/**
 * Lab screens for the responsive matrix, besides /lab (listed in e2e/routes.ts). Owned by the
 * lab module. Data comes from the backend fixtures `lab_order` (a paid CBC and malaria test)
 * and `lab_progress` (moves a test along the bench), built once per worker. Each `ready` waits
 * for loaded content, never for the page heading alone.
 */
import type { Locator, Page } from "@playwright/test";

import { fixture, seededCatalog } from "../helpers";
import { appRoute, type AppRoute } from "../route-kit";

interface LabOrder {
  patient: { id: number; file_no: string };
  visit: { id: number; number: string };
  lab_lines: { id: number; service: string }[];
}

interface LabProgress {
  line: number;
  sample: { id: number; accession_no: string };
  stage: string;
  versions: { id: number; version_no: number; status: string }[];
}

interface Bench {
  entered: LabProgress;
  amended: LabProgress;
}

let bench: Promise<Bench> | undefined;

/** One paid order: CBC entered with a critical haemoglobin, malaria approved then amended. */
function benchOnce(): Promise<Bench> {
  bench ??= (async () => {
    const order = await fixture<LabOrder>("lab_order", {
      tests: ["LAB-CBC", "LAB-BFMP"],
      patient_fields: { full_name_en: "Amna Hassan Ali Mohamed" },
    });
    const [cbc, bfmp] = order.lab_lines;
    if (!cbc || !bfmp) throw new Error("lab_order returned no lines");
    const entered = await fixture<LabProgress>("lab_progress", {
      line: cbc.id,
      stage: "entered",
      values: { WBC: "7.2", HGB: "5.1", PLT: "260" },
    });
    const amended = await fixture<LabProgress>("lab_progress", {
      line: bfmp.id,
      stage: "amended",
      values: { MP: "positive" },
      amended_values: { MP: "negative" },
    });
    return { entered, amended };
  })();
  return bench;
}

/** The first loaded row of a lab list: a card on phones, a table row from md up. */
function firstRow(page: Page, cardTestId: string): Locator {
  return page
    .locator(
      `[data-testid="${cardTestId}"], ` +
        '[data-slot="data-table"][data-mode="table"] tbody tr:not(:has([data-slot="skeleton"])):not(:has(td[colspan]))',
    )
    .first();
}

export const routes: readonly AppRoute[] = [
  appRoute("lab-result-entry", "/lab/results/$lineId", {
    resolve: async () => `/lab/results/${String((await benchOnce()).entered.line)}`,
    ready: (page) => page.getByTestId("approval-panel"),
  }),
  appRoute("lab-result-amended", "/lab/results/$lineId", {
    resolve: async () => `/lab/results/${String((await benchOnce()).amended.line)}`,
    ready: (page) => page.getByTestId("version-history"),
  }),
  appRoute("lab-result-print", "/lab/results/$lineId/print", {
    resolve: async () => `/lab/results/${String((await benchOnce()).amended.line)}/print`,
    ready: (page) => page.getByTestId("result-print"),
  }),
  appRoute("lab-label", "/lab/samples/$sampleId/label", {
    resolve: async () => `/lab/samples/${String((await benchOnce()).entered.sample.id)}/label`,
    ready: (page) => page.getByTestId("sample-label"),
  }),
  appRoute("lab-approve", "/lab/approve", {
    resolve: async () => {
      await benchOnce();
      return "/lab/approve";
    },
    ready: (page) => firstRow(page, "approval-row"),
  }),
  appRoute("lab-catalog", "/lab/catalog", {
    ready: (page) => firstRow(page, "catalog-row"),
  }),
  appRoute("lab-catalog-test", "/lab/catalog/$testId", {
    resolve: async () => {
      const id = (await seededCatalog()).lab_tests["LAB-CBC"];
      if (id === undefined) throw new Error("No seeded CBC test");
      return `/lab/catalog/${String(id)}`;
    },
    ready: (page) => page.getByTestId("parameter-row").first(),
  }),
  appRoute("lab-tat", "/lab/tat", {
    ready: (page) => firstRow(page, "tat-row"),
  }),
];
