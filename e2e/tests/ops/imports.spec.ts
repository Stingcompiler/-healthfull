/**
 * Excel imports from the administration wizard (FEATURES 1.8, 8.13): a patient sheet with one
 * invalid row shows that row's error in the preview and imports the others; a stock item
 * sheet with opening stock creates the item and its stock reaches the shelves through a
 * goods receipt (the item page shows it). Filter with `make e2e E2E_GREP=@ops`.
 */
import { expect, test, type Page } from "@playwright/test";

import { ANONYMOUS_STATE } from "../../fixtures/state";
import { apiAs, disposeApiClients, expectNoHorizontalScroll, login, setPrefs, snap, tr } from "../../helpers";
import { importSheet, itemRow, phoneDigits, runTag, type UploadFile } from "./kit";

test.describe.configure({ timeout: 180_000 });
test.use({ storageState: ANONYMOUS_STATE });
test.afterAll(disposeApiClients);

async function upload(page: Page, file: UploadFile): Promise<void> {
  await page.locator("#import-file").setInputFiles(file);
  await page.getByRole("button", { name: tr("en", "ops:imports.check") }).click();
}

async function confirmImport(page: Page): Promise<void> {
  await page
    .locator("main")
    .getByRole("button", { name: tr("en", "ops:imports.confirm"), exact: true })
    .click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: tr("en", "ops:imports.confirm"), exact: true }).click();
  await expect(dialog).toBeHidden();
}

test.describe("@ops imports", () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test("a patient sheet with one invalid row shows its error and imports the rest", async ({ page }) => {
    const tag = runTag();
    const file = await importSheet("patients", [
      [`مريض أول ${tag}`, `First ${tag}`, "M", "1990-01-02", "", `09${phoneDigits()}`],
      [`مريضة ثانية ${tag}`, `Second ${tag}`, "F", "", 34, `09${phoneDigits()}`],
      ["", "", "F", "", 20, ""],
    ]);
    await login(page, "admin");
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/administration/imports");
    await expect(page.locator("#main h1")).toHaveText(tr("en", "admin:sections.imports.title"));
    await upload(page, file);

    // Problems first: the row without a name, with its translated error.
    const table = page.locator("main");
    await expect(table.getByText(tr("en", "errors:NAME_REQUIRED"))).toBeVisible();
    await expect(
      page.locator("main").getByText(tr("en", "ops:imports.willImport_other", { count: "2" })),
    ).toBeVisible();
    await expectNoHorizontalScroll(page);
    await snap(page, "ops-imports-preview");

    await confirmImport(page);
    await expect(page.getByText(tr("en", "ops:imports.doneTitle_other", { count: "2" })).first()).toBeVisible();
    await page.getByRole("tab", { name: tr("en", "ops:imports.filterImported") }).click();
    await expect(table.getByRole("link", { name: `First ${tag}` })).toBeVisible();
    await snap(page, "ops-imports-done");

    const admin = await apiAs("admin");
    const found = await admin.get<{ count: number }>(`/api/patients?q=${encodeURIComponent(tag)}`);
    expect(found.count).toBe(2);
  });

  test("an item sheet with opening stock creates the item and its stock", async ({ page }) => {
    const tag = runTag();
    const code = `DRG-E2E${tag}`;
    const file = await importSheet("items", [
      itemRow({
        service_code: code,
        name_ar: "زنك تجريبي",
        name_en: `Zinc ${tag}`,
        kind: "drug",
        generic_name: `Zinc sulfate ${tag}`,
        form: "tablet",
        strength: "20 mg",
        base_unit_code: "TAB",
        base_unit_name_ar: "قرص",
        base_unit_name_en: "tablet",
        pack_unit_code: "BOX",
        pack_unit_name_ar: "علبة",
        pack_unit_name_en: "box",
        pack_factor: 100,
        min_stock: 10,
        batch_no: `Z1-${tag}`,
        expiry_date: "2030-06-30",
        quantity: 250,
        unit_cost: "12.5",
        store: "PHA",
      }),
      // A second batch of the same item: the item columns may stay empty.
      itemRow({
        service_code: code,
        batch_no: `Z2-${tag}`,
        expiry_date: "2031-01-31",
        quantity: 40,
        unit_cost: "12",
        store: "PHA",
      }),
      // No base unit: an error row, never imported.
      itemRow({
        service_code: `DRG-BAD${tag}`,
        name_en: "No unit",
        generic_name: "No unit",
      }),
    ]);
    await login(page, "admin");
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/administration/imports");
    await page.locator("#import-kind-items").click();
    await upload(page, file);

    const table = page.locator("main");
    await expect(table.getByText(tr("en", "errors:UNIT_REQUIRED"))).toBeVisible();
    await expect(
      page.locator("main").getByText(tr("en", "ops:imports.willImport_other", { count: "2" })),
    ).toBeVisible();
    await confirmImport(page);
    await expect(page.getByText(tr("en", "ops:imports.doneTitle_other", { count: "2" })).first()).toBeVisible();
    await expect(page.getByText(/GRN-/).first()).toBeVisible();

    await page.getByRole("tab", { name: tr("en", "ops:imports.filterImported") }).click();
    await table
      .getByRole("link", { name: new RegExp(code) })
      .first()
      .click();
    await expect(page).toHaveURL(/\/pharmacy\/items\/\d+$/);
    // 250 + 40 tablets received as opening stock into the outpatient pharmacy.
    await expect(page.locator("main dl")).toContainText("290");
    await snap(page, "ops-imports-item-stock");
  });
});
