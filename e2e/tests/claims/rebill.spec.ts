/**
 * Partial rejection and rebill (FEATURES 11.4, 11.5; ARCHITECTURE 4.5): the payer accepts
 * 4,000 of a 7,000 claimed ECG share; the accountant records the answer on the line with the
 * payer's reason, then rebills the rejected 3,000 to the patient with a reason and the
 * manager's approval (ADR 0018). The patient
 * now owes it on the original invoice: the cashier desk shows the patient's outstanding
 * balance grow from the 3,000 patient share to 6,000.
 */
import { expect, test } from "@playwright/test";

import { E2E_PASSWORD } from "../../fixtures/users";
import { disposeApiClients } from "../../helpers";
import { choose, claimCase, claimLoaded, pageAs, rowAction, sdg, t } from "./kit";

test.describe("@claims rebill", () => {
  test.describe.configure({ timeout: 120_000 });
  test.afterAll(disposeApiClients);

  test("partial rejection, then rebill shows as patient outstanding", async ({ browser }) => {
    const made = await claimCase({ stage: "submitted", services: ["PRC-ECG"] });
    const claim = made.claim;
    if (!claim) throw new Error("claims_case returned no claim");
    const page = await pageAs(browser, "accountant");

    // Before: the patient owes the unpaid 3,000 patient share only.
    await page.goto(`/cashier?visit=${String(made.visit.id)}`);
    await expect(page.getByTestId("patient-balance")).toContainText(sdg("3000.00"));

    await page.goto(`/claims/${String(claim.id)}`);
    await claimLoaded(page);
    const line = page.locator("tr").filter({ hasText: made.patient.full_name_en });
    await rowAction(page, line, t("claims:detail.recordAnswer"));
    const dialog = page.getByTestId("response-dialog");
    await dialog.getByRole("radio", { name: t("claims:response.partial") }).click();
    // A rejected part needs the payer's reason; a partial must stay below the claimed amount.
    await dialog.getByLabel(t("claims:response.acceptedAmount")).fill("7000");
    await dialog.getByTestId("response-submit").click();
    await expect(dialog.getByText(t("claims:validation.partialRange"))).toBeVisible();
    await expect(dialog.getByText(t("claims:validation.payerReason"))).toBeVisible();
    await dialog.getByLabel(t("claims:response.acceptedAmount")).fill("4000");
    await dialog.getByLabel(t("claims:response.reason")).fill("Tariff limit for ECG");
    await dialog.getByTestId("response-submit").click();
    await expect(dialog).toBeHidden();
    await expect(line.locator('[data-stage="partially_accepted"]')).toBeVisible();
    await expect(page.getByTestId("claim-totals")).toContainText(sdg("4000.00"));

    // Rebill the rejected 3,000 to the patient, with a reason and a second person's approval
    // (invariant 4, ADR 0018: the manager types their own credentials).
    await rowAction(page, line, t("claims:detail.rebill"));
    const reason = page.getByTestId("resolve-dialog");
    await choose(page, t("claims:resolve.reason"), "Not covered");
    await reason.getByLabel(t("approver.username")).fill("manager");
    await reason.getByLabel(t("approver.password")).fill(E2E_PASSWORD);
    await reason.getByTestId("resolve-confirm").click();
    await expect(reason).toBeHidden();
    await expect(line.getByTestId("line-resolution")).toContainText(t("claims:resolution.rebilled"));

    // After: the patient owes the rebilled part on the same invoice.
    await page.goto(`/cashier?visit=${String(made.visit.id)}`);
    await expect(page.getByTestId("patient-balance")).toContainText(sdg("6000.00"));
    await expect(page.getByTestId("invoice-number").first()).toHaveText(made.invoice.number);
  });
});
