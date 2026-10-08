/**
 * FLOW step 4 at the cashier desk, keyboard first: open the shift, find the patient, invoice
 * the requested lines with the payer split (10,000 = 7,000 payer / 3,000 patient), approve,
 * take cash with change due, and print the receipt with its QR code.
 */
import { expect, test } from "@playwright/test";

import { createPatient, createVisit, disposeApiClients, orderLines } from "../../helpers";
import { lineRow, noShift, openVisit, pageAs, payer70, sdg, t } from "./kit";

test.describe("@cashier money flow", () => {
  test.describe.configure({ timeout: 120_000 });
  test.afterAll(disposeApiClients);

  test("insurance line split, approval, cash with change, receipt", async ({ browser }) => {
    const payer = await payer70();
    const { patient } = await createPatient({ payer });
    const { visit } = await createVisit({ patient });
    await orderLines({ visit, items: [{ service: "PRC-ECG" }] });
    await noShift("cashier");

    const page = await pageAs(browser, "cashier");
    await page.goto("/cashier");

    // Open the shift from the shift bar.
    await expect(page.getByTestId("shift-bar")).toHaveAttribute("data-shift-status", "none");
    await page.getByTestId("open-shift").click();
    const dialog = page.getByTestId("open-shift-dialog");
    await dialog.getByLabel(t("cashier:shift.openingFloat")).fill("5000");
    await dialog.getByTestId("open-shift-submit").click();
    await expect(page.getByTestId("shift-bar")).toHaveAttribute("data-shift-status", "open");

    // F2 focuses the lookup.
    await page.keyboard.press("F2");
    await expect(page.getByTestId("cashier-lookup")).toBeFocused();
    await openVisit(page, patient.file_no, visit.number);

    // Requested lines: the consultation and the ECG, all selected. F4 drafts the invoice.
    const unbilled = page.getByTestId("unbilled-lines");
    await expect(unbilled.getByTestId("unbilled-line")).toHaveCount(2);
    await expect(unbilled.locator('[data-status="requested"]')).toHaveCount(2);
    await page.keyboard.press("F4");

    const draft = page.getByTestId("draft-invoice");
    await expect(draft).toBeVisible();
    const ecg = lineRow(draft, "Electrocardiogram");
    await expect(ecg.getByTestId("payer-share")).toHaveText(/7,000\.00/);
    await expect(ecg.getByTestId("patient-share")).toHaveText(/3,000\.00/);
    const consult = lineRow(draft, "General consultation");
    await expect(consult.getByTestId("payer-share")).toHaveText(/10,500\.00/);
    await expect(consult.getByTestId("patient-share")).toHaveText(/4,500\.00/);

    // F8 asks to approve the draft; prices freeze and the invoice is numbered.
    await page.keyboard.press("F8");
    await page.getByRole("alertdialog").getByRole("button", { name: t("cashier:invoice.approve") }).click();
    const invoice = page.getByTestId("approved-invoice");
    await expect(invoice.getByTestId("invoice-number")).toHaveText(/^INV-/);
    await expect(invoice.locator('[data-status="invoiced"]')).toHaveCount(2);
    await expect(invoice.getByTestId("invoice-totals")).toContainText(sdg("7500.00"));

    // Cash: the amount defaults to what is owed; 10,000 handed over leaves 2,500 change.
    const payment = page.getByTestId("payment-panel");
    await expect(payment.getByLabel(t("cashier:payment.amount"))).toHaveValue("7500.00");
    await payment.getByLabel(t("cashier:payment.tendered")).fill("10000");
    await expect(payment.getByTestId("change-due")).toContainText(sdg("2500.00"));
    // The app reads Ctrl on the emulated (non-Mac) desktop browser.
    await page.keyboard.press("Control+Enter");
    await expect(payment.getByTestId("payment-done")).toContainText(sdg("7500.00"));
    await expect(payment.getByTestId("payment-done")).toContainText(sdg("2500.00"));

    // Fully paid: both lines are paid and leave for the departments' work lists.
    await expect(invoice.locator('[data-status="paid"]')).toHaveCount(2);
    await expect(page.getByTestId("patient-balance")).toContainText(sdg("0.00"));

    // Receipt with its verification QR, in 80 mm and A4.
    await payment.getByTestId("print-receipt").click();
    await expect(page.getByTestId("receipt-number")).toHaveText(/^RCP-/);
    await expect(page.getByTestId("receipt-qr")).toBeVisible();
    await expect(page.getByTestId("receipt")).toContainText(sdg("7500.00"));
    await page.getByTestId("format-a4").click();
    await expect(page.locator('[data-print-root][data-print-format="a4"]')).toBeVisible();

    // The shift report counts the cash as confirmed collection.
    await page.goto("/cashier/shift");
    await expect(page.getByTestId("report-confirmed-total")).toContainText(sdg("7500.00"));
    await page.context().close();
  });
});
