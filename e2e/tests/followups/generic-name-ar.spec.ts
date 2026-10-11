/**
 * Phase 8 follow-up (FEATURES 8.1, 8.8): an item's Arabic generic name is entered on the item
 * page and shown by the Arabic stock lists; English screens keep the Latin name, and an item
 * without an Arabic name shows the Latin one everywhere.
 * Filter with `make e2e E2E_GREP=@followups`.
 */
import { expect, test } from "@playwright/test";

import { ANONYMOUS_STATE } from "../../fixtures/state";
import {
  apiAs,
  disposeApiClients,
  expectNoHorizontalScroll,
  login,
  seededCatalog,
  setPrefs,
  snap,
  tr,
} from "../../helpers";

test.describe.configure({ timeout: 120_000 });
test.use({ storageState: ANONYMOUS_STATE });

const ARABIC = "أموكسيسيلين";

async function amoxicillin(): Promise<number> {
  const item = (await seededCatalog()).items["DRG-AMOX500"];
  if (!item) throw new Error("the seeded amoxicillin item is missing");
  return item.id;
}

test.afterAll(async () => {
  // Leave the seeded item as the other specs know it.
  const pharmacist = await apiAs("pharmacist");
  await pharmacist.patch(`/api/pharmacy/items/${String(await amoxicillin())}`, { generic_name_ar: "" });
  await disposeApiClients();
});

test.describe("@followups @pharmacy Arabic generic name", () => {
  test("entered on the item, shown by the Arabic expiry list", async ({ page }) => {
    const id = await amoxicillin();
    await page.setViewportSize({ width: 768, height: 1024 });
    await login(page, "pharmacist");
    await setPrefs(page, { theme: "light", lang: "en" });
    // The item master takes the Arabic name.
    await page.goto(`/pharmacy/items/${String(id)}`);
    const editForm = page.getByTestId("item-edit-form");
    await editForm.getByLabel(tr("en", "pharmacy:items.fields.genericNameAr")).fill(ARABIC);
    await editForm.getByTestId("item-edit-save").click();
    const pharmacist = await apiAs("pharmacist");
    await expect
      .poll(
        async () =>
          (await pharmacist.get<{ generic_name_ar: string }>(`/api/pharmacy/items/${String(id)}`)).generic_name_ar,
      )
      .toBe(ARABIC);

    // Amoxicillin has a batch expiring within 30 days (seed): Arabic screens show its Arabic name.
    await setPrefs(page, { theme: "warm", lang: "ar" });
    await page.goto("/pharmacy/expiry");
    await expect(page.locator("#main")).toContainText(ARABIC);
    await expectNoHorizontalScroll(page);
    await snap(page, "followups-generic-name-ar");
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/pharmacy/expiry");
    await expect(page.locator("#main")).toContainText("Amoxicillin");
    await expect(page.locator("#main")).not.toContainText(ARABIC);
  });
});
