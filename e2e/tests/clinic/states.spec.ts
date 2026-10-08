/**
 * The clinic's busiest states through the responsive matrix (ARCHITECTURE 5.3 and 6), as a
 * doctor sees them: a queue with waiting, called and in-progress patients, the orders tab with
 * a drug in the draft, the allergy override dialog and the allergy manager. Three viewports x
 * (ar light, en dark, ar warm), no horizontal scroll, screenshots to artifacts/screens/.
 * The general matrix (tests/responsive.spec.ts) runs as the admin, whose clinic queue is empty.
 * Filter with `make e2e E2E_GREP=@clinic`.
 */
import { expect, test, type Page } from "@playwright/test";

import { ANONYMOUS_STATE } from "../../fixtures/state";
import {
  apiAs,
  disposeApiClients,
  expectNoHorizontalScroll,
  login,
  paidVisit,
  setPrefs,
  snap,
  trackConsoleErrors,
  type Lang,
  type Theme,
} from "../../helpers";

const DOCTOR = "pediatrician" as const;
const VIEWPORTS = [
  { width: 375, height: 812 },
  { width: 768, height: 1024 },
  { width: 1280, height: 800 },
] as const;
const COMBOS: readonly { theme: Theme; lang: Lang }[] = [
  { theme: "light", lang: "ar" },
  { theme: "dark", lang: "en" },
  { theme: "warm", lang: "ar" },
];

interface WorklistRow {
  id: number;
  status: string;
}

test.describe.configure({ mode: "serial", timeout: 120_000 });
test.use({ storageState: ANONYMOUS_STATE });

let workspaceVisit = 0;

async function drain(): Promise<void> {
  const doctor = await apiAs(DOCTOR);
  const rows = await doctor.get<WorklistRow[]>("/api/clinical/worklist");
  const steps: Record<string, string[]> = {
    waiting: ["call", "start", "complete"],
    called: ["start", "complete"],
    in_progress: ["complete"],
  };
  for (const row of rows) {
    for (const action of steps[row.status] ?? []) {
      await doctor.post(`/api/clinical/worklist/${String(row.id)}/action`, {
        action,
      });
    }
  }
}

test.beforeAll(async () => {
  await drain();
  const doctor = await apiAs(DOCTOR);
  const busy = await paidVisit({
    doctor: DOCTOR,
    patient_fields: {
      allergies: ["PENICILLIN"],
      full_name_en: "Mohamed Abdelrahim Osman Elhassan",
    },
  });
  const called = await paidVisit({
    doctor: DOCTOR,
    patient_fields: { allergies: ["NSAID"] },
  });
  await paidVisit({
    doctor: DOCTOR,
    patient_fields: { full_name_en: "Hiba Salah Eldin Ahmed" },
  });
  const rows = await doctor.get<(WorklistRow & { visit: { id: number } })[]>(
    "/api/clinical/worklist",
  );
  const entry = (visitId: number) =>
    rows.find((r) => r.visit.id === visitId)?.id;
  for (const action of ["call", "start"]) {
    await doctor.post(
      `/api/clinical/worklist/${String(entry(busy.visit.id))}/action`,
      { action },
    );
  }
  await doctor.post(
    `/api/clinical/worklist/${String(entry(called.visit.id))}/action`,
    { action: "call" },
  );
  workspaceVisit = busy.visit.id;
});

test.afterAll(async () => {
  await drain();
  await disposeApiClients();
});

async function check(page: Page, name: string): Promise<void> {
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  await expectNoHorizontalScroll(page);
  await snap(page, name);
}

for (const viewport of VIEWPORTS) {
  for (const { theme, lang } of COMBOS) {
    test(`@clinic @responsive doctor states ${String(viewport.width)} ${theme} ${lang}`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      // The allergy alert is a 409 answer by design.
      const logged = trackConsoleErrors(page, { allowAnonymousMe: true });
      await login(page, DOCTOR);
      await setPrefs(page, { theme, lang });

      // The populated queue: waiting, called and with the doctor, allergy chips on the cards.
      await page.goto("/clinic");
      // Ours are the three active ones; patients seen earlier today may follow.
      await expect(page.getByTestId("queue-entry").nth(2)).toBeVisible();
      await check(page, "clinic-queue");

      // Orders tab with a drug in the draft and the prescription builder.
      await page.goto(`/clinic/visits/${String(workspaceVisit)}`);
      await page.getByTestId("tab-orders").click();
      const search = page.getByTestId("catalog-search");
      await search.fill("DRG-AMOX500");
      await expect(search).toHaveAttribute("data-fresh", "true");
      await page
        .getByTestId("catalog-results")
        .locator('[data-service-code="DRG-AMOX500"]')
        .click();
      const rx = page.locator(
        '[data-testid="draft-item"][data-service-code="DRG-AMOX500"]',
      );
      await rx.getByTestId("rx-frequency").click();
      await page.getByTestId("rx-frequency-TID").click();
      await rx.getByTestId("rx-days").fill("5");
      await expect(rx.getByTestId("rx-quantity")).toContainText("15");
      await check(page, "clinic-visit-orders-draft");

      // The allergy override dialog.
      await page.getByTestId("place-orders").click();
      const dialog = page.getByTestId("allergy-override-dialog");
      await expect(dialog).toBeVisible();
      await check(page, "clinic-visit-override");
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();

      // The allergy manager.
      await page.getByTestId("manage-allergies").click();
      await expect(page.getByTestId("allergy-form")).toBeVisible();
      await check(page, "clinic-visit-allergies");
      await page.keyboard.press("Escape");

      expect(
        logged.errors().filter((e) => !/status of 409/.test(e)),
        "console errors",
      ).toEqual([]);
    });
  }
}
