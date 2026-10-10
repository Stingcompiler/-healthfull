/**
 * The public receipt check behind the QR (FEATURES 15.1): anyone can open it without signing
 * in; it shows only what proves the receipt and never the patient's name.
 */
import { expect, test } from "@playwright/test";

import { apiAs, disposeApiClients } from "../../helpers";
import { phonePage, portalPatient, t } from "./kit";

test.describe("@portal receipt verification", () => {
  test.describe.configure({ timeout: 120_000 });
  test.afterAll(disposeApiClients);

  test("the QR verification page works", async ({ browser }) => {
    const who = await portalPatient({ code: false });
    // The printed receipt carries the token the QR opens.
    const cashier = await apiAs("cashier");
    const receipt = await cashier.get<{ verify_token: string; payment: { patient: { full_name_en: string } } }>(
      `/api/payments/payments/${String(who.payment.id)}/receipt`,
    );
    expect(receipt.verify_token).toBe(who.verify_token);

    const page = await phonePage(browser);
    await page.goto(`/verify/${who.verify_token}?r=${encodeURIComponent(who.payment.number)}`);
    const result = page.getByTestId("verify-result");
    await expect(result).toHaveAttribute("data-status", "valid");
    await expect(page.getByText(t("portal:verify.status.valid"))).toBeVisible();
    await expect(page.getByTestId("verify-number")).toHaveText(who.payment.number);
    const text = (await page.locator("#main").textContent()) ?? "";
    expect(text).not.toContain(receipt.payment.patient.full_name_en);
    expect(text).not.toContain(who.patient.file_no);

    // A token that is not the receipt's own proves nothing.
    await page.goto(`/verify/${"a".repeat(20)}?r=${encodeURIComponent(who.payment.number)}`);
    await expect(page.getByText(t("portal:verify.notFound"))).toBeVisible();
    await expect(page.getByTestId("verify-result")).toHaveCount(0);
  });
});
