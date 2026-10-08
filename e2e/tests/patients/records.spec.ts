/**
 * Patient records and the flows that touch invariants or permissions (FEATURES 0.9, 1.4-1.6,
 * 2.3, 2.6, 2.7): merge with a reason, coverage on file, the balance only for the cash side,
 * cancelling a paid visit (supervisor only, credit note on the timeline), the global quick
 * search, emergencies on the board, the no-show confirmation, failures shown with a retry,
 * and the token slip's print layout.
 */
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { SCREENS_DIR } from "../../env";

import {
  apiAs,
  createPatient,
  createVisit,
  disposeApiClients,
  expectNoHorizontalScroll,
  login,
  paidVisit,
  setPrefs,
  snap,
  tr,
  type Lang,
} from "../../helpers";

test.describe.configure({ timeout: 120_000 });
test.afterAll(disposeApiClients);

type Who = Parameters<typeof login>[1];

async function signIn(page: Page, who: Who, lang: Lang, theme: "light" | "dark" | "warm" = "light"): Promise<void> {
  await login(page, who);
  await setPrefs(page, { theme, lang });
}

async function chooseOption(page: Page, label: string, option: string | RegExp): Promise<void> {
  await page.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option }).first().click();
}

function unique(): string {
  return String(Date.now()).slice(-7);
}

test("@patients merge a duplicate file with a reason", async ({ page }) => {
  const name = `خديجة الماحي ${unique()}`;
  const { patient: keep } = await createPatient({ full_name_ar: name, full_name_en: "Khadija Almahi" });
  const { patient: duplicate } = await createPatient({ full_name_ar: name });
  await page.setViewportSize({ width: 1280, height: 800 });
  await signIn(page, "manager", "en", "dark");
  await page.goto(`/patients/${String(keep.id)}`);

  await page.getByRole("button", { name: tr("en", "patients:merge.open") }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("searchbox").fill(duplicate.file_no);
  await dialog.getByRole("button", { name: new RegExp(duplicate.file_no) }).click();
  // Focus follows the pick: the "change" action replaces the result that had focus.
  const change = dialog.getByRole("button", { name: tr("en", "patients:picker.change") });
  await expect(change).toBeFocused();
  await dialog.getByRole("button", { name: tr("en", "common:actions.continue") }).click();

  const reason = page.getByRole("dialog");
  await expect(reason.getByTestId("merge-summary")).toContainText(duplicate.file_no);
  await reason.getByRole("combobox").click();
  await page.getByRole("option", { name: "Registered twice" }).click();
  await reason.getByRole("textbox").fill("Same mother, registered at two desks");
  await reason.getByRole("button", { name: tr("en", "patients:merge.confirm") }).click();
  await expect(reason).toHaveCount(0);

  const history = page.getByTestId("merge-history");
  await expect(history).toContainText(duplicate.file_no);
  await expect(history).toContainText("Registered twice");
  await expect(history).toContainText("Same mother, registered at two desks");

  // The merged file says where it went.
  await page.goto(`/patients/${String(duplicate.id)}`);
  await expect(page.getByText(tr("en", "patients:profile.mergedTitle"))).toBeVisible();
});

test("@patients add, edit and end a coverage on file", async ({ page }) => {
  const { patient } = await createPatient({ full_name_ar: `عمر صالح ${unique()}` });
  await page.setViewportSize({ width: 768, height: 1024 });
  await signIn(page, "reception", "ar", "warm");
  await page.goto(`/patients/${String(patient.id)}`);
  await expect(page.getByText(tr("ar", "patients:coverage.none"))).toBeVisible();

  await page.getByRole("button", { name: tr("ar", "patients:coverage.add") }).click();
  const dialog = page.getByRole("dialog");
  await chooseOption(page, tr("ar", "patients:coverage.payer"), /الأمان/);
  await dialog.getByLabel(tr("ar", "patients:coverage.cardNumber")).fill("AMN-7001");
  await dialog.getByRole("button", { name: tr("ar", "common:actions.save") }).click();
  await expect(dialog).toHaveCount(0);
  const row = page.getByTestId("coverage");
  await expect(row).toContainText("AMN-7001");
  await expect(row).toContainText(tr("ar", "patients:coverage.default"));

  await row.getByRole("button", { name: /تعديل|Edit/ }).first().click();
  const edit = page.getByRole("dialog");
  await edit.getByLabel(tr("ar", "patients:coverage.cardNumber")).fill("AMN-7002");
  await edit.getByRole("button", { name: tr("ar", "common:actions.save") }).click();
  await expect(row).toContainText("AMN-7002");
  await expectNoHorizontalScroll(page);

  await row.getByRole("button").last().click();
  await page.getByRole("alertdialog").getByRole("button", { name: tr("ar", "patients:coverage.end") }).click();
  await expect(page.getByTestId("coverage")).toHaveCount(0);
  await expect(page.getByText(tr("ar", "patients:coverage.none"))).toBeVisible();
});

test("@patients the balance shows at the cash desk, not at reception", async ({ page }) => {
  const ready = await paidVisit({ doctor: "doctor", patient_fields: { full_name_ar: `هالة النور ${unique()}` } });
  await signIn(page, "cashier", "en");
  await page.goto(`/patients/${String(ready.patient.id)}`);
  const balance = page.getByTestId("balance");
  await expect(balance).toBeVisible();
  await expect(balance).toContainText(tr("en", "patients:balance.credit"));

  await signIn(page, "reception", "en");
  await page.goto(`/patients/${String(ready.patient.id)}`);
  await expect(page.locator('[data-slot="patient-card"]')).toBeVisible();
  await expect(page.getByTestId("balance")).toHaveCount(0);
});

test("@patients a paid visit is cancelled by a supervisor with a credit note", async ({ page }) => {
  const ready = await paidVisit({ doctor: "doctor", patient_fields: { full_name_ar: `يوسف بشير ${unique()}` } });

  // Reception is told before typing a reason that a supervisor must do it.
  await page.setViewportSize({ width: 375, height: 812 });
  await signIn(page, "reception", "ar");
  await page.goto(`/patients/${String(ready.patient.id)}`);
  const item = page.getByTestId("visit-item").first();
  await item.getByRole("button", { name: tr("ar", "visits:cancel.open") }).click();
  const blocked = page.getByTestId("cancel-needs-supervisor");
  await expect(blocked).toContainText(tr("ar", "visits:cancel.needsSupervisorTitle"));
  await expectNoHorizontalScroll(page);
  await snap(page, "dialog-cancel-needs-supervisor");
  await page.keyboard.press("Escape");

  // The cashier supervisor cancels it: the paid fee is credited and the visit is cancelled.
  await page.setViewportSize({ width: 1280, height: 800 });
  await signIn(page, "cashsup", "en", "dark");
  await page.goto(`/patients/${String(ready.patient.id)}`);
  const visit = page.getByTestId("visit-item").first();
  await visit.getByRole("button", { name: tr("en", "visits:cancel.open") }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(tr("en", "visits:cancel.descriptionBilled"));
  await dialog.getByRole("combobox").click();
  await page.getByRole("option", { name: "Patient left" }).click();
  await dialog.getByRole("button", { name: tr("en", "visits:cancel.confirm") }).click();
  await expect(dialog).toHaveCount(0);
  await expect(visit).toContainText(tr("en", "visits:visitStatus.cancelled"));
  await visit.getByRole("button", { name: tr("en", "visits:timeline.title") }).click();
  await expect(visit).toContainText(tr("en", "visits:timeline.kind.credit_note"));
  await expect(visit).toContainText(tr("en", "visits:timeline.kind.visit_cancelled"));
  // The paid money is now patient credit.
  await expect(page.getByTestId("balance")).not.toContainText(tr("en", "patients:balance.settled"));
});

test("@patients the quick search finds a patient by name and opens the file", async ({ page }) => {
  const suffix = unique();
  const { patient } = await createPatient({ full_name_en: `Quicksearch Person ${suffix}`, full_name_ar: `بحث سريع ${suffix}` });
  await signIn(page, "reception", "en");
  await page.goto("/");
  await page.keyboard.press("Control+k");
  const menu = page.getByRole("dialog");
  await menu.getByRole("combobox").fill(`Quicksearch Person ${suffix}`);
  const hit = menu.getByTestId("quick-search-patient").filter({ hasText: patient.file_no });
  await expect(hit).toBeVisible();
  await hit.click();
  await expect(page).toHaveURL(new RegExp(`/patients/${String(patient.id)}$`));

  // By file number in Arabic too.
  await setPrefs(page, { theme: "light", lang: "ar" });
  await page.keyboard.press("Control+k");
  await page.getByRole("dialog").getByRole("combobox").fill(patient.file_no);
  await expect(page.getByRole("dialog").getByTestId("quick-search-patient")).toContainText(`بحث سريع ${suffix}`);
});

test("@patients emergencies are marked on the board and a no-show needs confirmation", async ({ page }) => {
  const { patient } = await createPatient({ full_name_ar: `طوارئ ${unique()}` });
  await createVisit({ patient: patient.id, doctor: null, department: "ER", visit_type: "emergency" });
  const reception = await apiAs("reception");
  const options = await reception.get<{ departments: { id: number; code: string; name_en: string }[] }>(
    "/api/visits/options",
  );
  const er = options.departments.find((d) => d.code === "ER");
  expect(er).toBeDefined();

  for (const width of [1280, 375]) {
    await page.setViewportSize({ width, height: width > 400 ? 800 : 812 });
    await signIn(page, "reception", "en");
    await page.goto("/queue");
    await chooseOption(page, tr("en", "visits:board.department"), er?.name_en ?? "");
    const row = (width > 400 ? page.getByRole("row") : page.getByTestId("queue-card")).filter({
      hasText: patient.file_no,
    });
    await expect(row.getByTestId("emergency-badge")).toBeVisible();
    await expect(row.getByTestId("emergency-badge")).toContainText(tr("en", "visits:board.emergency"));
    await expectNoHorizontalScroll(page);
  }

  const card = page.getByTestId("queue-card").filter({ hasText: patient.file_no });
  await card.getByRole("button", { name: tr("en", "common:table.rowActions") }).click();
  await page.getByRole("menuitem", { name: tr("en", "visits:board.action.no_show") }).click();
  const confirm = page.getByRole("alertdialog");
  await expect(confirm).toContainText(tr("en", "visits:board.noShowConfirmTitle"));
  await confirm.getByRole("button", { name: tr("en", "common:actions.cancel") }).click();
  await expect(card.getByText(tr("en", "visits:queueStatus.waiting"))).toBeVisible();

  await card.getByRole("button", { name: tr("en", "common:table.rowActions") }).click();
  await page.getByRole("menuitem", { name: tr("en", "visits:board.action.no_show") }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: tr("en", "visits:board.action.no_show") }).click();
  await expect(card.getByText(tr("en", "visits:queueStatus.no_show"))).toBeVisible();
});

test("@patients a failed request shows an error with a retry, not an empty list", async ({ page }) => {
  await signIn(page, "reception", "en");
  await page.route("**/api/patients?**", (route) => route.abort());
  await page.goto("/patients");
  const alert = page.getByRole("alert").filter({ hasText: tr("en", "patients:list.loadFailed") });
  await expect(alert).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(tr("en", "patients:list.emptyTitle"))).toHaveCount(0);
  await page.unroute("**/api/patients?**");
  await alert.getByTestId("query-retry").click();
  await expect(alert).toHaveCount(0);
  await expect(page.getByRole("searchbox")).toBeVisible();
});

test("@patients the waiting-room kiosk has no way into the app and says when it is offline", async ({ page }) => {
  await signIn(page, "reception", "ar");
  await page.goto("/display/queue");
  await expect(page.locator("#display-now")).toBeVisible();
  // No shell, no links into the staff screens, no quick search.
  await expect(page.locator('[data-slot="app-bottom-nav"]')).toHaveCount(0);
  await expect(page.locator("a[href]")).toHaveCount(0);
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await page.route("**/api/visits/queue/display**", (route) => route.abort());
  await expect(page.getByTestId("display-offline")).toBeVisible({ timeout: 45_000 });
  await expect(page.locator("#display-now")).toHaveCount(0);
  await expectNoHorizontalScroll(page);
  await page.unroute("**/api/visits/queue/display**");
  await expect(page.locator("#display-now")).toBeVisible({ timeout: 30_000 });
});

test("@patients the token slip prints on an 80 mm page", async ({ page }) => {
  const { patient } = await createPatient({ full_name_ar: `إيصال ${unique()}`, full_name_en: "Slip Print" });
  const { queue_entry: entry } = await createVisit({ patient: patient.id, doctor: "doctor" });
  expect(entry).not.toBeNull();
  for (const lang of ["ar", "en"] as const) {
    await signIn(page, "reception", lang);
    await page.goto("/queue");
    const row = page.getByRole("row").filter({ hasText: patient.file_no });
    await row.getByRole("button", { name: tr(lang, "common:table.rowActions") }).click();
    await page.getByRole("menuitem", { name: tr(lang, "visits:board.action.print") }).click();
    await expect(page.getByRole("dialog").getByTestId("token-slip")).toContainText(patient.file_no);

    await page.emulateMedia({ media: "print" });
    const printed = page.locator("#token-print-root");
    await expect(printed).toBeVisible();
    await expect(page.getByRole("dialog")).toBeHidden();
    const box = await printed.locator(":scope > div").boundingBox();
    expect(box?.width ?? 0).toBeLessThanOrEqual(80 * 3.78 + 1); // 80 mm in CSS px
    const pageRule = await page.evaluate(() =>
      [...document.styleSheets]
        .flatMap((sheet) => [...sheet.cssRules])
        .map((rule) => rule.cssText)
        .find((text) => text.includes("@page")),
    );
    expect(pageRule ?? "").toMatch(/size:\s*80mm 150mm/);
    await printed.screenshot({ path: path.join(SCREENS_DIR, `token-slip-print-${lang}.png`) });
    await page.emulateMedia({ media: "screen" });
    await page.keyboard.press("Escape");
  }
});

test("@patients import patients from a sheet with preview and duplicates", async ({ page }) => {
  const suffix = unique();
  const phone = `09${suffix.padStart(8, "1")}`;
  const { patient: existing } = await createPatient({ full_name_ar: `موجود سابقاً ${suffix}`, phone });
  const csv = [
    "الاسم بالعربية,Name (English),Sex,Age (years),Phone",
    `مستورد أول ${suffix},Imported One ${suffix},ذكر,34,`,
    `,,female,20,`,
    `موجود سابقاً ${suffix},,M,40,${phone}`,
  ].join("\n");

  await page.setViewportSize({ width: 1280, height: 800 });
  await signIn(page, "admin", "en", "dark");
  await page.goto("/patients");
  await page.getByRole("link", { name: tr("en", "patients:import.open") }).click();
  await expect(page.locator("#main h1")).toHaveText(tr("en", "patients:import.title"));
  await expect(page.getByRole("link", { name: tr("en", "patients:import.templateAr") })).toHaveAttribute(
    "href",
    /\/api\/imports\/patients\/template\?language=ar/,
  );
  await page.getByLabel(tr("en", "patients:import.file")).setInputFiles({
    name: "patients.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(`﻿${csv}`, "utf8"),
  });
  await page.getByRole("button", { name: tr("en", "patients:import.check") }).click();

  const table = page.getByRole("table");
  await expect(table.getByRole("row")).toHaveCount(3); // header + the error + the duplicate
  await expect(table).toContainText(tr("en", "errors:NAME_REQUIRED"));
  await expect(table).toContainText(existing.file_no);
  await expectNoHorizontalScroll(page);
  await snap(page, "patient-import-preview");

  await page.getByRole("button", { name: tr("en", "patients:import.confirm") }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: tr("en", "patients:import.confirm") }).click();
  await expect(page.getByText(tr("en", "patients:import.doneTitle_one"))).toBeVisible();
  const imported = page.getByRole("link", { name: `Imported One ${suffix}` });
  await expect(imported).toBeVisible();
  await imported.click();
  await expect(page).toHaveURL(/\/patients\/\d+$/);
  await expect(page.locator('[data-slot="patient-card"]')).toContainText(/PT-\d{4}-\d+/);
});

test("@patients dialogs fit a phone", async ({ page }) => {
  const { patient } = await createPatient({ full_name_ar: `حوار الهاتف ${unique()}` });
  await createVisit({ patient: patient.id, doctor: "doctor" });
  await page.setViewportSize({ width: 375, height: 812 });
  await signIn(page, "admin", "ar");
  await page.goto(`/patients/${String(patient.id)}`);

  await page.getByRole("button", { name: tr("ar", "patients:profile.moreActions") }).click();
  await page.getByRole("menuitem", { name: tr("ar", "patients:merge.open") }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expectNoHorizontalScroll(page);
  await snap(page, "dialog-merge");
  await page.keyboard.press("Escape");

  await page.getByTestId("visit-item").first().getByRole("button", { name: tr("ar", "visits:cancel.open") }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expectNoHorizontalScroll(page);
  await snap(page, "dialog-cancel-visit");
  await page.keyboard.press("Escape");

  await page.goto("/appointments");
  await page.getByRole("button", { name: tr("ar", "visits:appointments.nextDay") }).first().click();
  await page.getByTestId("free-slot").first().getByRole("button").click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expectNoHorizontalScroll(page);
  await snap(page, "dialog-book-appointment");
});
