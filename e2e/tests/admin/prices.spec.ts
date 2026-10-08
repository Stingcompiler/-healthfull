/**
 * Administration: catalog and price lists (FEATURES 5.1, 5.2, invariant 6). A new service gets a
 * price in a scheduled version of a new list; a bulk +10% update shows before/after prices and
 * creates a new version effective on the chosen date, leaving the earlier versions unchanged.
 */
import { expect, test, type Page } from "@playwright/test";

import { ADMIN_STATE } from "../../fixtures/state";
import { setPrefs, tr } from "../../helpers";

/** ISO date at the center (Africa/Khartoum), `days` from today. */
function centerDate(days: number): string {
  const shifted = new Date(Date.now() + days * 86_400_000);
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Africa/Khartoum",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(shifted);
}

/** A new version from `date`; a list's first version may start empty (`copy: "empty"`) or, by
 * default, from the current prices of the cash list (pre-selected). */
async function newVersion(page: Page, date: string, copy: "default" | "empty" = "default"): Promise<void> {
  await page.getByRole("button", { name: tr("en", "admin:prices.newVersion") }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel(tr("en", "admin:prices.effectiveFrom")).fill(date);
  const copyFrom = dialog.getByRole("combobox", { name: tr("en", "admin:prices.copyFrom") });
  if (copy === "empty") {
    await copyFrom.click();
    await page.getByRole("option", { name: tr("en", "admin:prices.startEmpty") }).click();
  } else if ((await copyFrom.count()) > 0) {
    // The cash list is pre-selected once the lists have loaded.
    await expect(copyFrom).not.toContainText(tr("en", "admin:prices.startEmpty"));
  }
  await dialog.getByRole("button", { name: tr("en", "actions.save") }).click();
  await expect(page.getByText(tr("en", "admin:prices.versionCreated")).first()).toBeVisible();
  await expect(dialog).toBeHidden();
}

test.describe("@admin catalog and prices", () => {
  test.use({ storageState: ADMIN_STATE });
  test.describe.configure({ mode: "serial", timeout: 90_000 });

  const stamp = String(Date.now()).slice(-6);
  const serviceCode = `E2E-XRAY-${stamp}`;
  const listCode = `E2EPL${stamp}`;
  const todayListCode = `E2ETD${stamp}`;

  test("create a service, a price list and a priced version; bulk +10% makes a new dated version", async ({
    page,
  }) => {
    await setPrefs(page, { theme: "light", lang: "en" });

    // 1. A new catalog service.
    await page.goto("/administration/catalog");
    await page.getByRole("button", { name: tr("en", "admin:catalog.add") }).click();
    let dialog = page.getByRole("dialog");
    await dialog.getByLabel(tr("en", "admin:common.code")).fill(serviceCode);
    await dialog.getByLabel(tr("en", "admin:common.nameEn")).fill("Chest X-ray e2e");
    await dialog.getByLabel(tr("en", "admin:common.nameAr")).fill("أشعة صدر");
    await dialog.getByRole("button", { name: tr("en", "actions.save") }).click();
    await expect(dialog).toBeHidden();
    await page.getByRole("searchbox").fill(serviceCode);
    await expect(page.locator("main").getByText("Chest X-ray e2e").first()).toBeVisible();

    const newList = async (code: string, nameEn: string) => {
      await page.goto("/administration/price-lists");
      await page.getByRole("button", { name: tr("en", "admin:prices.addList") }).click();
      dialog = page.getByRole("dialog");
      await dialog.getByLabel(tr("en", "admin:common.code")).fill(code);
      await dialog.getByLabel(tr("en", "admin:common.nameEn")).fill(nameEn);
      await dialog.getByLabel(tr("en", "admin:common.nameAr")).fill("عقد تجريبي");
      await dialog.getByRole("button", { name: tr("en", "actions.save") }).click();
      await expect(page).toHaveURL(/\/administration\/price-lists\/\d+$/);
      await expect(page.locator("#main h1")).toHaveText(nameEn);
    };

    // 2. A new price list can go live today, but only with prices: an empty same-day version
    // would be locked at once with nothing in it. It copies the cash list's current prices.
    await newList(todayListCode, "E2E contract today");
    await page.getByRole("button", { name: tr("en", "admin:prices.newVersion") }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByLabel(tr("en", "admin:prices.effectiveFrom")).fill(centerDate(0));
    await dialog.getByRole("combobox", { name: tr("en", "admin:prices.copyFrom") }).click();
    await page.getByRole("option", { name: tr("en", "admin:prices.startEmpty") }).click();
    await dialog.getByRole("button", { name: tr("en", "actions.save") }).click();
    await expect(dialog.getByText(tr("en", "admin:prices.copyRequiredToday"))).toBeVisible();
    await dialog.getByRole("button", { name: tr("en", "actions.cancel") }).click();
    await newVersion(page, centerDate(0));
    const today = page.getByTestId(`version-${centerDate(0)}`);
    await expect(today).toContainText(tr("en", "admin:prices.status.current"));
    await expect(today).not.toContainText(tr("en", "admin:prices.items_other", { count: "0" }));
    await expect(page.getByText(tr("en", "admin:prices.lockedTitle"))).toBeVisible();
    await expect(page.getByTestId(/^price-/)).toHaveCount(0); // read-only: prices are text

    // 3. Another new list starts empty from tomorrow; that version is editable.
    await newList(listCode, "E2E contract");
    await newVersion(page, centerDate(1), "empty");
    await expect(page.getByTestId(`version-${centerDate(1)}`)).toHaveAttribute("aria-current", "true");
    // The empty version explains itself and offers the same action as the toolbar.
    await expect(page.getByText(tr("en", "admin:empty.priceItems.title"))).toBeVisible();
    await page.getByRole("button", { name: tr("en", "admin:prices.addService") }).first().click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("searchbox").fill(serviceCode);
    await dialog.getByRole("combobox", { name: tr("en", "admin:prices.service") }).click();
    await page.getByRole("option", { name: new RegExp(serviceCode) }).click();
    await dialog.getByLabel(tr("en", "admin:prices.unitPrice")).fill("15000");
    await dialog.getByRole("button", { name: tr("en", "actions.save") }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByTestId(`price-${serviceCode}`)).toHaveValue("15000.00");

    // Editing a price of a scheduled version.
    await page.getByTestId(`price-${serviceCode}`).fill("16000");
    await page.getByRole("button", { name: tr("en", "admin:prices.saveChanges") }).click();
    await expect(page.getByRole("button", { name: tr("en", "admin:prices.saveChanges") })).toBeHidden();
    await expect(page.getByTestId(`price-${serviceCode}`)).toHaveValue("16000.00");
    await page.getByTestId(`price-${serviceCode}`).fill("15000");
    await page.getByRole("button", { name: tr("en", "admin:prices.saveChanges") }).click();
    await expect(page.getByTestId(`price-${serviceCode}`)).toHaveValue("15000.00");

    // 4. Bulk +10% from a chosen date: preview before/after, then a new dated version.
    const chosen = centerDate(5);
    await page.getByRole("button", { name: tr("en", "admin:prices.bulk") }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByLabel(tr("en", "admin:prices.percent")).fill("10");
    await dialog.getByLabel(tr("en", "admin:prices.effectiveFrom")).fill(chosen);
    await dialog.getByRole("button", { name: tr("en", "admin:prices.preview") }).click();
    await expect(dialog.getByText(tr("en", "admin:prices.previewTitle")).first()).toBeVisible();
    await expect(dialog.getByText("15,000.00").first()).toBeVisible();
    await expect(dialog.getByText("16,500.00").first()).toBeVisible();
    await dialog.getByTestId("bulk-apply").click();
    await expect(dialog).toBeHidden();

    const created = page.getByTestId(`version-${chosen}`);
    await expect(created).toBeVisible();
    await expect(created).toHaveAttribute("aria-current", "true");
    await expect(created).toContainText(tr("en", "admin:prices.status.scheduled"));
    await expect(created).toContainText(tr("en", "admin:prices.percentChange", { value: "+10%" }));
    await expect(page.getByTestId(`price-${serviceCode}`)).toHaveValue("16500.00");

    // The base version keeps its price (a bulk update never edits an existing version).
    await page.getByTestId(`version-${centerDate(1)}`).click();
    await expect(page.getByTestId(`price-${serviceCode}`)).toHaveValue("15000.00");

    // 5. A mistaken scheduled version is withdrawn with a reason before it starts.
    await created.click();
    await page.getByRole("button", { name: tr("en", "admin:prices.withdraw") }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: tr("en", "admin:prices.withdraw") }).click();
    await expect(dialog.getByText(tr("en", "validation.required"))).toBeVisible();
    await dialog.getByLabel(tr("en", "admin:common.reason")).fill("Meant for next month");
    await dialog.getByRole("button", { name: tr("en", "admin:prices.withdraw") }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText(tr("en", "admin:prices.withdrawn")).first()).toBeVisible();
    await expect(page.getByTestId(`version-${chosen}`)).toHaveCount(0);
    // The version that is in effect today offers no withdrawal.
    await page.goto("/administration/price-lists");
    await page.locator("main").getByText(todayListCode).first().click();
    await expect(page.getByTestId(`version-${centerDate(0)}`)).toBeVisible();
    await expect(page.getByRole("button", { name: tr("en", "admin:prices.withdraw") })).toHaveCount(0);
  });
});
