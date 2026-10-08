/**
 * Administration: payers and coverage rules (FEATURES 5.5, 5.7, 11.1). While a rule is edited,
 * the example split is computed by the backend's coverage rule: 10,000 at 70% gives the payer
 * 7,000 and the patient 3,000; a copay of 2,000 gives 8,000 / 2,000.
 */
import { expect, test } from "@playwright/test";

import { ADMIN_STATE } from "../../fixtures/state";
import { setPrefs, tr } from "../../helpers";

test.describe("@admin payers", () => {
  test.use({ storageState: ADMIN_STATE });
  test.describe.configure({ timeout: 60_000 });

  test("a payer's coverage rule shows a live example split", async ({ page }) => {
    const code = `E2EPAY${String(Date.now()).slice(-6)}`;
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/administration/payers");
    await page.getByRole("button", { name: tr("en", "admin:payers.add") }).click();
    let dialog = page.getByRole("dialog");
    await dialog.getByLabel(tr("en", "admin:common.code")).fill(code);
    await dialog.getByLabel(tr("en", "admin:common.nameEn")).fill("Nile Insurance e2e");
    await dialog.getByLabel(tr("en", "admin:common.nameAr")).fill("النيل للتأمين");
    await dialog.getByRole("button", { name: tr("en", "actions.save") }).click();
    await expect(page).toHaveURL(/\/administration\/payers\/\d+$/);
    await expect(page.locator("#main h1")).toHaveText("Nile Insurance e2e");

    // A default percentage rule: the example follows every keystroke.
    await page.getByRole("button", { name: tr("en", "admin:payers.addRule") }).click();
    dialog = page.getByRole("dialog");
    await expect(dialog.getByText(tr("en", "admin:payers.exampleIncomplete"))).toBeVisible();
    await dialog.getByLabel(tr("en", "admin:payers.payerPercent")).fill("70");
    await expect(dialog.getByTestId("example-payer")).toContainText("7,000.00");
    await expect(dialog.getByTestId("example-patient")).toContainText("3,000.00");

    // Another example amount.
    await dialog.getByLabel(tr("en", "admin:payers.exampleGross")).fill("25000");
    await expect(dialog.getByTestId("example-payer")).toContainText("17,500.00");
    await expect(dialog.getByTestId("example-patient")).toContainText("7,500.00");
    await dialog.getByLabel(tr("en", "admin:payers.exampleGross")).fill("10000");

    // Switching to a fixed copay recomputes the split.
    await dialog.getByRole("radio", { name: tr("en", "admin:payers.ruleKinds.copay") }).check();
    await dialog.getByLabel(tr("en", "admin:payers.copayAmount")).fill("2000");
    await expect(dialog.getByTestId("example-payer")).toContainText("8,000.00");
    await expect(dialog.getByTestId("example-patient")).toContainText("2,000.00");

    // Save the 70% rule.
    await dialog.getByRole("radio", { name: tr("en", "admin:payers.ruleKinds.percentage") }).check();
    await expect(dialog.getByTestId("example-payer")).toContainText("7,000.00");
    await dialog.getByRole("button", { name: tr("en", "actions.save") }).click();
    await expect(dialog).toBeHidden();
    await expect(page.locator("main").getByText(tr("en", "admin:payers.summary.percentage", { percent: "70.00" }))).toBeVisible();
    await expect(page.locator("main").getByText(tr("en", "admin:payers.defaultScope")).first()).toBeVisible();

    // A second default rule is refused with a translated message.
    await page.getByRole("button", { name: tr("en", "admin:payers.addRule") }).click();
    dialog = page.getByRole("dialog");
    await dialog.getByLabel(tr("en", "admin:payers.payerPercent")).fill("50");
    await dialog.getByRole("button", { name: tr("en", "actions.save") }).click();
    await expect(dialog.getByText(tr("en", "errors:COVERAGE_RULE_DUPLICATE"))).toBeVisible();
  });
});
