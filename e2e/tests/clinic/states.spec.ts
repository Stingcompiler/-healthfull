/**
 * The clinic's busiest states through the responsive matrix (ARCHITECTURE 5.3 and 6), as a
 * doctor sees them: a queue with waiting, called and in-progress patients, a workspace that
 * failed to load, open ICD-10 and catalog result lists, the referral form and the reason asked
 * to cancel one, the orders tab with a drug in the draft (marked for its allergy), the favorite,
 * allergy override and withdrawal dialogs, the allergy and condition managers, and the history
 * and results tabs. Three viewports x (ar light, en dark, ar warm), no horizontal scroll,
 * screenshots to artifacts/screens/.
 * The general matrix (tests/responsive.spec.ts) runs as the admin, whose clinic queue is empty.
 * Filter with `make e2e E2E_GREP=@clinic`.
 */
import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { SCREENS_DIR } from "../../env";
import { ANONYMOUS_STATE } from "../../fixtures/state";
import {
  apiAs,
  disposeApiClients,
  expectNoHorizontalScroll,
  login,
  paidVisit,
  seededCatalog,
  setPrefs,
  snap,
  tr,
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
  const catalog = await seededCatalog();
  // An earlier visit of the busy patient, seen and diagnosed: the history tab has content.
  const earlier = await paidVisit({
    doctor: DOCTOR,
    patient_fields: {
      allergies: ["PENICILLIN"],
      full_name_en: "Mohamed Abdelrahim Osman Elhassan",
    },
  });
  const first = await doctor.get<(WorklistRow & { visit: { id: number } })[]>(
    "/api/clinical/worklist",
  );
  const earlierEntry = first.find((r) => r.visit.id === earlier.visit.id)?.id;
  for (const action of ["call", "start"]) {
    await doctor.post(`/api/clinical/worklist/${String(earlierEntry)}/action`, {
      action,
    });
  }
  await doctor.post(`/api/clinical/visits/${String(earlier.visit.id)}/diagnoses`, {
    text: "Uncomplicated malaria",
  });
  await doctor.post(`/api/clinical/worklist/${String(earlierEntry)}/action`, {
    action: "complete",
  });
  const busy = await paidVisit({
    doctor: DOCTOR,
    patient: earlier.patient.id,
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
  // A placed (withdrawable) order and an issued referral of the doctor's own.
  const cbc = catalog.services["LAB-CBC"];
  if (!cbc) throw new Error("LAB-CBC is seeded");
  await doctor.post(`/api/orders/visits/${String(busy.visit.id)}/lines`, {
    items: [{ service_id: cbc.id }],
  });
  await doctor.post(`/api/clinical/visits/${String(busy.visit.id)}/referrals`, {
    kind: "external",
    reason: "CT scan of the chest",
    external_facility: "Soba University Hospital",
  });
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

/**
 * A modal state: the overlay and the dialog are fixed to the viewport, so a full-page capture
 * would show them over a scrolled slice of the page. Capture what the doctor sees instead,
 * under the same file name scheme as `snap`.
 */
async function checkDialog(
  page: Page,
  name: string,
  theme: Theme,
  lang: Lang,
): Promise<void> {
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  await expectNoHorizontalScroll(page);
  const size = page.viewportSize();
  const viewport = size ? `${String(size.width)}x${String(size.height)}` : "auto";
  mkdirSync(SCREENS_DIR, { recursive: true });
  await page.screenshot({
    path: path.join(SCREENS_DIR, `${name}-${viewport}-${theme}-${lang}.png`),
    animations: "disabled",
    caret: "hide",
    scale: "css",
  });
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

      // The workspace when the server fails: the error card with a retry (before any draft, so
      // leaving needs no confirmation).
      const workspaceUrl = `/clinic/visits/${String(workspaceVisit)}`;
      await page.route("**/api/clinical/visits/*/workspace", (route) =>
        route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ code: "SERVER_ERROR", message: "", details: {} }),
        }),
      );
      await page.goto(workspaceUrl);
      // Two retries with backoff come first (lib/query.ts).
      await expect(
        page.getByText(tr(lang, "clinic:workspace.loadError")),
      ).toBeVisible({ timeout: 15_000 });
      await check(page, "clinic-visit-error");
      await page.unroute("**/api/clinical/visits/*/workspace");

      // An open ICD-10 result list on the note tab.
      await page.goto(workspaceUrl);
      const icd10 = page.getByTestId("icd10-search");
      await icd10.fill("malaria");
      const icdResults = page.getByTestId("icd10-results");
      await expect(icdResults).toBeVisible();
      await icdResults.scrollIntoViewIfNeeded();
      await checkDialog(page, "clinic-visit-icd10-results", theme, lang);
      await icd10.press("Escape");
      await expect(icdResults).toBeHidden();

      // The referral form, and the reason asked to cancel an issued referral.
      await page
        .getByRole("button", { name: tr(lang, "clinic:referral.new") })
        .click();
      await expect(page.getByRole("dialog")).toBeVisible();
      await checkDialog(page, "clinic-visit-referral", theme, lang);
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog")).toBeHidden();
      await page
        .getByRole("button", { name: tr(lang, "clinic:referral.cancel") })
        .first()
        .click();
      await expect(page.getByRole("dialog")).toContainText(
        tr(lang, "clinic:referral.cancelTitle"),
      );
      await checkDialog(page, "clinic-visit-referral-cancel", theme, lang);
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog")).toBeHidden();

      // Orders tab: an open catalog list, then a drug in the draft and the prescription builder.
      await page.getByTestId("tab-orders").click();
      const search = page.getByTestId("catalog-search");
      await search.fill("DRG-AMOX500");
      await expect(search).toHaveAttribute("data-fresh", "true");
      const amoxResult = page
        .getByTestId("catalog-results")
        .locator('[data-service-code="DRG-AMOX500"]');
      // The patient's penicillin allergy marks the drug before it is even added.
      await expect(amoxResult).toHaveAttribute("data-allergy", "true");
      await amoxResult.scrollIntoViewIfNeeded();
      await checkDialog(page, "clinic-visit-catalog-results", theme, lang);
      await amoxResult.click();
      const rx = page.locator(
        '[data-testid="draft-item"][data-service-code="DRG-AMOX500"]',
      );
      await expect(rx).toHaveAttribute("data-allergy", "true");
      await rx.getByTestId("rx-frequency").click();
      await page.getByTestId("rx-frequency-TID").click();
      await rx.getByTestId("rx-days").fill("5");
      await expect(rx.getByTestId("rx-quantity")).toContainText("15");
      // A full-page capture from the top: sticky bars stay where the doctor sees them.
      await page.evaluate(() => {
        window.scrollTo(0, 0);
      });
      await check(page, "clinic-visit-orders-draft");

      // The favorite dialog.
      await page.getByTestId("save-favorite").click();
      await expect(page.getByRole("dialog")).toBeVisible();
      await checkDialog(page, "clinic-visit-favorite", theme, lang);
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog")).toBeHidden();

      // The allergy override dialog.
      await page.getByTestId("place-orders").click();
      const dialog = page.getByTestId("allergy-override-dialog");
      await expect(dialog).toBeVisible();
      await checkDialog(page, "clinic-visit-override", theme, lang);
      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      // Dismissing the override keeps the drug marked.
      await expect(rx).toHaveAttribute("data-allergy", "true");

      // The reason asked to withdraw a placed order.
      await page
        .locator('[data-testid="order-line"][data-service-code="LAB-CBC"]')
        .getByRole("button", { name: tr(lang, "clinic:orders.withdraw") })
        .click();
      await expect(page.getByRole("dialog")).toContainText(
        tr(lang, "clinic:orders.withdrawTitle"),
      );
      await checkDialog(page, "clinic-visit-withdraw", theme, lang);
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog")).toBeHidden();

      // The allergy manager.
      await page.getByTestId("manage-allergies").click();
      await expect(page.getByTestId("allergy-form")).toBeVisible();
      await checkDialog(page, "clinic-visit-allergies", theme, lang);
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog")).toBeHidden();

      // The chronic condition manager (behind the summary toggle below lg).
      const toggle = page.getByTestId("summary-toggle");
      if (await toggle.isVisible()) await toggle.click();
      await page.getByTestId("manage-conditions").click();
      await expect(page.getByRole("dialog")).toBeVisible();
      await checkDialog(page, "clinic-visit-conditions", theme, lang);
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog")).toBeHidden();

      // History with the earlier visit, and results (none until the lab module reports).
      await page.getByTestId("tab-history").click();
      await expect(page.getByText("Uncomplicated malaria")).toBeVisible();
      await page.evaluate(() => {
        window.scrollTo(0, 0);
      });
      await check(page, "clinic-visit-history");
      await page.getByTestId("tab-results").click();
      await expect(
        page.getByText(tr(lang, "clinic:results.emptyTitle")),
      ).toBeVisible();
      await page.evaluate(() => {
        window.scrollTo(0, 0);
      });
      await check(page, "clinic-visit-results");

      // 409: the allergy alert, by design; 500: the forced workspace error above.
      expect(
        logged.errors().filter((e) => !/status of (409|500)/.test(e)),
        "console errors",
      ).toEqual([]);
    });
  }
}
