/**
 * Administration: the permission matrix (FEATURES 0.3). Granting a permission to a role in the
 * grid gives every user of that role access at once; revoking it takes the access away again.
 */
import { expect, test, type Browser, type Page } from "@playwright/test";

import { ADMIN_STATE, ANONYMOUS_STATE } from "../../fixtures/state";
import { apiAs, disposeApiClients, login, reseed, setPrefs, tr } from "../../helpers";

const CELL = "perm-receptionist-core.manage_settings";

async function receptionistPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ storageState: ANONYMOUS_STATE });
  const page = await context.newPage();
  await login(page, "reception");
  // Logged in, this saves English to the profile too (it wins over the browser cache).
  await setPrefs(page, { theme: "light", lang: "en" });
  return page;
}

async function saveMatrix(page: Page, reason: string): Promise<void> {
  await page.getByRole("button", { name: tr("en", "admin:roles.save") }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(tr("en", "admin:common.reason")).fill(reason);
  await dialog.getByRole("button", { name: tr("en", "actions.save") }).click();
  await expect(page.getByText(tr("en", "admin:roles.saved"))).toBeVisible();
}

test.describe("@admin permission matrix", () => {
  test.use({ storageState: ADMIN_STATE });

  test.afterAll(async () => {
    // Back to the default matrix whatever happened above.
    const admin = await apiAs("admin");
    await admin.put("/api/core/permissions/matrix", {
      changes: [{ role: "receptionist", code: "core.manage_settings", allowed: false }],
      reason: "e2e cleanup",
    });
    await disposeApiClients();
    // The receptionist's saved language goes back to the seed value.
    reseed();
  });

  test("granting and revoking a permission changes what the role can open", async ({ page, browser }) => {
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/administration/roles");
    const cell = page.getByTestId(CELL);
    await expect(cell).toBeVisible();
    await expect(cell).not.toBeChecked();

    // Before: the receptionist has no administration entry and the page refuses.
    const desk = await receptionistPage(browser);
    await expect(desk.locator("aside").getByTestId("nav-admin")).toHaveCount(0);
    await desk.goto("/administration/policies");
    await expect(desk.getByText(tr("en", "admin:noAccess.title"))).toBeVisible();

    // Grant core.manage_settings to the receptionist role.
    await cell.check();
    await expect(page.getByText(tr("en", "admin:roles.pending_one", { count: "1" }))).toBeVisible();
    await saveMatrix(page, "Pilot: front desk keeps the policies");
    await expect(cell).toBeChecked();

    await desk.goto("/administration/policies");
    await expect(desk.locator("#main h1")).toHaveText(tr("en", "admin:sections.policies.title"));
    await expect(desk.getByText(tr("en", "admin:policies.payFirst"))).toBeVisible();
    await expect(desk.locator("aside").getByTestId("nav-admin")).toBeVisible();

    // Revoke it again: access is gone.
    await page.reload();
    await page.getByTestId(CELL).uncheck();
    await saveMatrix(page, "Pilot over");
    await desk.goto("/administration/policies");
    await expect(desk.getByText(tr("en", "admin:noAccess.title"))).toBeVisible();
    const status = await desk.evaluate(async () => (await fetch("/api/core/policy")).status);
    expect(status).toBe(403);
    await desk.context().close();
  });
});
