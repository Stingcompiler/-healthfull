/**
 * Administration: payers and coverage rules (FEATURES 5.5, 5.7, 11.1). While a rule is edited,
 * the example split is computed by the backend's coverage rule: 10,000 at 70% gives the payer
 * 7,000 and the patient 3,000; a copay of 2,000 gives 8,000 / 2,000.
 *
 * Works on the seeded AMAN payer (70% default rule) and saves nothing, so the seed catalog other
 * specs rely on stays as it is.
 */
import { expect, test } from "@playwright/test";

import { ADMIN_STATE } from "../../fixtures/state";
import { seededCatalog, setPrefs, tr } from "../../helpers";

test.describe("@admin payers", () => {
  test.use({ storageState: ADMIN_STATE });
  test.describe.configure({ timeout: 60_000 });

  test("a payer's coverage rule shows a live example split", async ({ page }) => {
    const aman = (await seededCatalog()).payers.AMAN;
    expect(aman).toBeDefined();
    await setPrefs(page, { theme: "light", lang: "en" });

    // The payers list opens the payer.
    await page.goto("/administration/payers");
    const main = page.locator("main");
    await main.getByText("AMAN", { exact: true }).first().click();
    await expect(page).toHaveURL(new RegExp(`/administration/payers/${String(aman?.id)}$`));
    await expect(page.locator("#main h1")).toBeVisible();
    await expect(main.getByText(tr("en", "admin:payers.defaultScope")).first()).toBeVisible();

    // Edit the default 70% rule: the example follows every keystroke.
    await main.getByText(tr("en", "admin:payers.defaultScope")).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByLabel(tr("en", "admin:payers.payerPercent"))).toHaveValue("70.00");
    await expect(dialog.getByTestId("example-payer")).toContainText("7,000.00");
    await expect(dialog.getByTestId("example-patient")).toContainText("3,000.00");

    await dialog.getByLabel(tr("en", "admin:payers.exampleGross")).fill("25000");
    await expect(dialog.getByTestId("example-payer")).toContainText("17,500.00");
    await expect(dialog.getByTestId("example-patient")).toContainText("7,500.00");
    await dialog.getByLabel(tr("en", "admin:payers.exampleGross")).fill("10000");

    await dialog.getByLabel(tr("en", "admin:payers.payerPercent")).fill("80");
    await expect(dialog.getByTestId("example-payer")).toContainText("8,000.00");
    await expect(dialog.getByTestId("example-patient")).toContainText("2,000.00");

    // A fixed copay recomputes the split; a ceiling caps the payer.
    await dialog.getByRole("radio", { name: tr("en", "admin:payers.ruleKinds.copay") }).check();
    await dialog.getByLabel(tr("en", "admin:payers.copayAmount")).fill("2000");
    await expect(dialog.getByTestId("example-payer")).toContainText("8,000.00");
    await expect(dialog.getByTestId("example-patient")).toContainText("2,000.00");
    await dialog.getByRole("radio", { name: tr("en", "admin:payers.ruleKinds.ceiling") }).check();
    await dialog.getByLabel(tr("en", "admin:payers.ceilingAmount")).fill("6000");
    await dialog.getByLabel(tr("en", "admin:payers.payerPercentOptional")).fill("");
    await expect(dialog.getByTestId("example-payer")).toContainText("6,000.00");
    await expect(dialog.getByTestId("example-patient")).toContainText("4,000.00");

    // Leave without saving: the rule is unchanged.
    await dialog.getByRole("button", { name: tr("en", "actions.cancel") }).click();
    await expect(dialog).toBeHidden();
    await expect(main.getByText(tr("en", "admin:payers.summary.percentage", { percent: "70.00" })).first()).toBeVisible();

    // A second default rule is refused with a translated message (nothing is saved).
    await page.getByRole("button", { name: tr("en", "admin:payers.addRule") }).click();
    await dialog.getByLabel(tr("en", "admin:payers.payerPercent")).fill("50");
    await expect(dialog.getByTestId("example-payer")).toContainText("5,000.00");
    await dialog.getByRole("button", { name: tr("en", "actions.save") }).click();
    await expect(dialog.getByText(tr("en", "errors:COVERAGE_RULE_DUPLICATE"))).toBeVisible();
  });
});
