/**
 * Claim batch (FEATURES 11.3): the accountant builds a claim from one payer's insurance lines,
 * leaves one share out for a later batch, marks the claim sent, and exports it. The Excel
 * download is a real workbook (a zip with the workbook, sheet and shared strings) that names
 * the claim, the payer and the patients' services.
 */
import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { disposeApiClients } from "../../helpers";
import { claimCase, claimLoaded, pageAs, sdg, t, unzip } from "./kit";

test.describe("@claims build and export", () => {
  test.describe.configure({ timeout: 120_000 });
  test.afterAll(disposeApiClients);

  test("build a claim from insurance lines, mark it sent, export a valid xlsx", async ({ browser }) => {
    // ECG 10,000, CBC 12,000 and FBS 4,000 at 70%: the payer owes 7,000 + 8,400 + 2,800.
    const made = await claimCase({
      services: ["PRC-ECG", "LAB-CBC", "LAB-FBS"],
    });
    const page = await pageAs(browser, "accountant");

    // The receivables show the payer's accrued share; nothing is collected yet.
    await page.goto("/claims");
    const payerRow = page.locator("tr").filter({ hasText: made.payer.name_en });
    await expect(payerRow).toContainText(sdg("18200.00"));

    await page.goto(`/claims/new?payer=${String(made.payer.id)}`);
    const lines = page.getByTestId("accrued-line");
    await expect(lines).toHaveCount(3);
    await expect(page.getByTestId("build-total")).toContainText(sdg("18200.00"));
    // Leave the FBS share out: it stays accrued for a later batch.
    const fbs = lines.filter({ hasText: "2,800.00" });
    await fbs.getByRole("checkbox").click();
    await expect(page.getByTestId("build-total")).toContainText(sdg("15400.00"));
    await page.getByTestId("build-submit").click();

    await expect(page).toHaveURL(/\/claims\/\d+$/);
    await claimLoaded(page);
    await expect(page.getByTestId("claim-totals")).toContainText(sdg("15400.00"));
    await expect(page.locator('[data-status="draft"]').first()).toBeVisible();
    const claimNumber = (await page.getByRole("heading", { level: 1 }).textContent()) ?? "";
    expect(claimNumber).toMatch(/CLM-/);

    await page.getByTestId("claim-submit").click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: t("claims:detail.submit") })
      .click();
    await expect(page.locator('[data-status="submitted"]').first()).toBeVisible();

    // The left-out share is still claimable.
    await page.goto(`/claims/new?payer=${String(made.payer.id)}`);
    await expect(page.getByTestId("accrued-line")).toHaveCount(1);
    await page.goBack();
    await claimLoaded(page);

    // Excel export: a workbook in the payer layout.
    const download = page.waitForEvent("download");
    await page.getByTestId("claim-export-en").click();
    const file = await download;
    expect(file.suggestedFilename()).toMatch(/^CLM-.*-en\.xlsx$/);
    const bytes = readFileSync(await file.path());
    expect(bytes.subarray(0, 4).toString("binary")).toBe("PK\u0003\u0004");
    const parts = unzip(bytes);
    expect([...parts.keys()]).toEqual(
      expect.arrayContaining(["[Content_Types].xml", "xl/workbook.xml", "xl/worksheets/sheet1.xml"]),
    );
    const strings = parts.get("xl/sharedStrings.xml") ?? "";
    const number = file.suggestedFilename().replace(/-en\.xlsx$/, "");
    expect(strings).toContain(number);
    expect(strings).toContain("Insurance claim");
    expect(strings).toContain(made.payer.name_en);
    expect(strings).toContain(made.invoice.number);
    expect(parts.get("xl/worksheets/sheet1.xml")).toContain("15400");
  });
});
