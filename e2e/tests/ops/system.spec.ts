/**
 * System pages (FEATURES 13.8, 13.9, 13.10, 0.4): the status page renders its checks and
 * records a manual backup request (there is no backup service in the e2e stack, so it waits);
 * the audit trail shows a change made a moment ago with who made it; the full export downloads
 * a zip. `make e2e E2E_GREP=@ops`.
 */
import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { ADMIN_STATE } from "../../fixtures/state";
import { apiAs, disposeApiClients, expectNoHorizontalScroll, fixture, setPrefs, snap, tr } from "../../helpers";
import { runTag } from "./kit";

test.describe.configure({ timeout: 120_000 });
test.use({ storageState: ADMIN_STATE, viewport: { width: 1280, height: 900 } });

test.afterAll(async () => {
  await fixture("ops_reset_backup_requests", {});
  await disposeApiClients();
});

test.describe("@ops system", () => {
  test("the status page renders and records a manual backup request", async ({ page }) => {
    await fixture("ops_reset_backup_requests", {});
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/administration/system");
    const main = page.locator("main");
    await expect(main.locator("h1")).toHaveText(tr("en", "admin:sections.system.title"));
    await expect(main.getByRole("heading", { name: tr("en", "ops:system.version"), exact: true })).toBeVisible();
    await expect(main.getByText(tr("en", "ops:system.dbOk"), { exact: true })).toBeVisible();
    await expect(main.getByRole("heading", { name: tr("en", "ops:system.disks") })).toBeVisible();
    await expect(main.getByRole("heading", { name: tr("en", "ops:system.updates") })).toBeVisible();
    // The e2e servers have no backup status folder: the page says so instead of guessing.
    await expect(main.getByText(tr("en", "ops:system.warnings.BACKUP_STATUS_UNAVAILABLE.title"))).toBeVisible();

    await main.getByRole("button", { name: tr("en", "ops:system.backupNow") }).click();
    const dialog = page.getByRole("alertdialog");
    await dialog.getByLabel(tr("en", "ops:system.backupNote")).fill("e2e check");
    await dialog.getByRole("button", { name: tr("en", "ops:system.backupNow") }).click();
    await expect(dialog).toBeHidden();
    await expect(main.getByText(tr("en", "ops:system.request.pending")).first()).toBeVisible();
    await expect(main.getByRole("button", { name: tr("en", "ops:system.backupNow") })).toBeDisabled();
    await expectNoHorizontalScroll(page);
    await snap(page, "ops-system-requested");
  });

  test("the audit trail shows a recent change with its author", async ({ page }) => {
    const code = `A${runTag()}`.slice(0, 10);
    const admin = await apiAs("admin");
    const dept = await admin.post<{ id: number }>("/api/core/departments", {
      code,
      name_ar: "قسم تدقيق",
      name_en: `Audit ${code}`,
    });
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/administration/audit");
    const main = page.locator("main");
    await expect(main.locator("h1")).toHaveText(tr("en", "admin:sections.audit.title"));
    await main.locator("#audit-model").click();
    await page
      .getByRole("option", {
        name: tr("en", "ops:audit.models.core_Department"),
      })
      .click();
    await main.locator("#audit-object").fill(String(dept.id));
    const event = main.getByTestId("audit-event").first();
    await expect(event).toContainText(tr("en", "ops:audit.actions.insert"));
    await expect(event).toContainText(code);
    await expect(event).toContainText(`Audit ${code}`);
    await expectNoHorizontalScroll(page);
    await snap(page, "ops-audit-event");
  });

  test("the full export downloads a zip", async ({ page }) => {
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/administration/export");
    const downloading = page.waitForEvent("download");
    await page.getByRole("button", { name: tr("en", "ops:export.download") }).click();
    const download = await downloading;
    expect(download.suggestedFilename()).toMatch(/^hospital-export-\d{8}-\d{4}\.zip$/);
    const file = await download.path();
    const bytes = readFileSync(file);
    expect(bytes.subarray(0, 4).toString("binary")).toBe("PK\u0003\u0004");
    expect(bytes.includes(Buffer.from("patients.csv"))).toBe(true);
    await expect(page.getByText(tr("en", "ops:export.done"))).toBeVisible();
  });
});
