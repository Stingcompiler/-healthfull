/**
 * Payer payment (FEATURES 11.6, 11.7; invariant 7): a payer's claim of 15,400 is accepted in
 * full. Until the payer pays, all of it is in the 0-30 day aging bucket. The accountant
 * records a bank transfer of 10,000 allocated to that claim; the aging falls to 5,400 and the
 * claim shows the payment.
 */
import { expect, test } from "@playwright/test";

import { disposeApiClients } from "../../helpers";
import { choose, claimCase, claimLoaded, pageAs, sdg, t } from "./kit";

test.describe("@claims payer payment", () => {
  test.describe.configure({ timeout: 120_000 });
  test.afterAll(disposeApiClients);

  test("payer payment allocation reduces aging", async ({ browser }) => {
    // ECG 10,000 and CBC 12,000 at 70%: 7,000 + 8,400 accepted.
    const made = await claimCase({
      stage: "answered",
      services: ["PRC-ECG", "LAB-CBC"],
    });
    const claim = made.claim;
    if (!claim) throw new Error("claims_case returned no claim");
    const page = await pageAs(browser, "accountant");

    await page.goto("/claims/aging");
    const row = page.locator("tr").filter({ hasText: made.payer.name_en });
    await expect(row).toContainText(sdg("15400.00"));

    await page.goto("/claims/payments");
    await page.getByTestId("record-payer-payment").click();
    const dialog = page.getByTestId("payer-payment-dialog");
    await choose(page, t("claims:payments.payer"), made.payer.name_en);
    // The accountant has no till: cash is not offered without an open shift.
    await expect(dialog.getByRole("radio", { name: t("claims:method.cash") })).toBeDisabled();
    await choose(page, t("claims:payments.bank"), "Bankak");
    await dialog.getByLabel(t("claims:payments.reference")).fill(`RA-${made.payer.code}-${String(Date.now())}`);
    await dialog.getByLabel(t("claims:payments.amount")).fill("10000");
    await dialog.getByRole("radio", { name: t("claims:payments.perClaim") }).click();
    const allocation = dialog.getByTestId("allocation-claims");
    await expect(allocation).toContainText(claim.number);
    await allocation.getByTestId("allocation-amount").fill("9000");
    await expect(allocation).toContainText(t("claims:payments.mustEqual"));
    await allocation.getByTestId("allocation-amount").fill("10000");
    await expect(dialog.getByTestId("allocation-total")).toContainText(sdg("10000.00"));
    await dialog.getByTestId("payer-payment-submit").click();
    await expect(dialog).toBeHidden();
    await expect(page.getByTestId("payment-recorded")).toContainText(t("claims:standingHint.bank"));

    await page.goto("/claims/aging");
    await expect(row).toContainText(sdg("5400.00"));
    await expect(row).not.toContainText(sdg("15400.00"));

    await page.goto(`/claims/${String(claim.id)}`);
    await claimLoaded(page);
    await expect(page.getByTestId("claim-payments")).toContainText(sdg("10000.00"));
    await expect(page.locator('[data-stage="paid"]')).toHaveCount(1);
  });
});
