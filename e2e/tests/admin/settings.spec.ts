/**
 * Administration: center profile and logo (FEATURES 13.1) and
 * reason lists (13.5).
 */
import { expect, test } from "@playwright/test";

import { ADMIN_STATE } from "../../fixtures/state";
import { apiAs, disposeApiClients, setPrefs, tr } from "../../helpers";

/** A 1x1 transparent PNG. */
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);

test.describe("@admin settings", () => {
  test.use({ storageState: ADMIN_STATE });
  test.afterAll(disposeApiClients);

  test("center profile and logo are saved and served from the server", async ({ page }) => {
    const admin = await apiAs("admin");
    const before = await admin.get<Record<string, string>>("/api/core/center");
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/administration/settings");
    const address = page.getByLabel(tr("en", "admin:settings.address"));
    await address.fill("Khartoum, Street 61");
    // Switching tabs would unmount the form: unsaved edits are asked about first.
    await page.getByRole("tab", { name: tr("en", "admin:settings.numberingTab") }).click();
    const discard = page.getByRole("alertdialog");
    await expect(discard.getByText(tr("en", "unsaved.discardTitle"))).toBeVisible();
    await discard.getByRole("button", { name: tr("en", "unsaved.stay") }).click();
    await expect(discard).toBeHidden();
    await expect(address).toHaveValue("Khartoum, Street 61");
    await page.getByRole("button", { name: tr("en", "admin:common.save") }).click();
    await expect(page.getByText(tr("en", "admin:settings.saved")).first()).toBeVisible();

    await page.getByTestId("logo-input").setInputFiles({ name: "logo.png", mimeType: "image/png", buffer: PNG });
    await expect(page.getByText(tr("en", "admin:settings.logoSaved"))).toBeVisible();
    const logo = page.getByRole("img", { name: tr("en", "admin:settings.logoAlt") });
    await expect(logo).toBeVisible();
    expect(await logo.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(1);

    // Removing the logo printed on every document asks first.
    await page.getByRole("button", { name: tr("en", "admin:settings.removeLogo") }).click();
    const confirm = page.getByRole("alertdialog");
    await expect(confirm.getByText(tr("en", "admin:settings.removeLogoTitle"))).toBeVisible();
    await confirm.getByRole("button", { name: tr("en", "admin:settings.removeLogo") }).click();
    await expect(page.getByText(tr("en", "admin:settings.logoRemoved"))).toBeVisible();
    await expect(page.getByText(tr("en", "admin:settings.noLogo"))).toBeVisible();

    // Put the seed values back.
    await admin.delete("/api/core/center/logo");
    await admin.put("/api/core/center", {
      name_ar: before.name_ar ?? "",
      name_en: before.name_en ?? "",
      address: before.address ?? "",
      phone: before.phone ?? "",
      registration_no: before.registration_no ?? "",
      tax_no: before.tax_no ?? "",
      digits: before.digits ?? "latin",
    });
  });

  test("a reason code is added to a reason list", async ({ page }) => {
    const code = `E2E_${String(Date.now()).slice(-6)}`;
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/administration/reason-codes");
    await page.getByRole("button", { name: tr("en", "admin:reasons.add") }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel(tr("en", "admin:common.code")).fill(code);
    await dialog.getByLabel(tr("en", "admin:reasons.labelEn")).fill(`Patient left before service ${code}`);
    await dialog.getByLabel(tr("en", "admin:reasons.labelAr")).fill("غادر المريض قبل الخدمة");
    // Listed last, so reason pickers in other specs keep their usual first choice.
    await dialog.getByLabel(tr("en", "admin:common.sortOrder")).fill("900");
    await dialog.getByRole("button", { name: tr("en", "actions.save") }).click();
    await expect(dialog).toBeHidden();
    await expect(page.locator("main").getByText(`Patient left before service ${code}`)).toBeVisible();
  });
});
