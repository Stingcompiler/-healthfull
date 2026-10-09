/**
 * Desk behaviours from the cashier review (FEATURES 6.5, 6.9, 7.6, 0.10):
 * - a payment goes to the visit on screen, never an older visit's invoice;
 * - cash handed to a supervisor waits until that supervisor confirms it;
 * - a receipt is checked by its number or QR, and a rejected transfer never stands;
 * - printing prints only the document on pages that have one, and other pages as they are.
 */
import { expect, test } from "@playwright/test";

import { approveInvoice, createPatient, createVisit, disposeApiClients, openShift, pay, tr } from "../../helpers";
import { choose, noShift, openVisit, pageAs, sdg, t } from "./kit";

test.describe("@cashier review fixes", () => {
  test.describe.configure({ timeout: 150_000 });
  test.afterAll(disposeApiClients);

  test("the payment pays the visit at the desk, other visits only when ticked", async ({ browser }) => {
    const { patient } = await createPatient();
    // An older visit's consultation (15,000) is still owed.
    const { visit: older } = await createVisit({ patient });
    const oldInvoice = await approveInvoice({ visit: older });
    // Today's visit with the pediatrician (20,000).
    const { visit } = await createVisit({ patient, doctor: "pediatrician" });
    await approveInvoice({ visit });
    await noShift("cashier");
    await openShift({ opening_float: "0" });

    const page = await pageAs(browser, "cashier");
    await openVisit(page, patient.file_no, visit.number);
    const payment = page.getByTestId("payment-panel");
    const amount = payment.getByLabel(t("cashier:payment.amount"));
    await expect(amount).toHaveValue("20000.00");
    await expect(payment).toContainText(sdg("15000.00"));
    await page.keyboard.press("Control+Enter");
    await expect(payment.getByTestId("payment-done")).toContainText(sdg("20000.00"));

    // The older visit is still owed in full; ticking it in fills its amount.
    await expect(page.getByTestId("approved-invoice").getByTestId("invoice-totals")).toContainText(sdg("0.00"));
    await payment.getByTestId("include-other-visits").click();
    await expect(amount).toHaveValue("15000.00");
    await page.goto(`/cashier?visit=${String(older.id)}`);
    const oldCard = page.locator(`[data-invoice-id="${String(oldInvoice.invoice.id)}"]`);
    await expect(oldCard.getByTestId("invoice-totals")).toContainText(sdg("15000.00"));
    await page.context().close();
  });

  test("cash handed to a supervisor is in transit until the supervisor receives it", async ({ browser }) => {
    await noShift("cashier");
    await openShift({ opening_float: "5000" });

    const cashier = await pageAs(browser, "cashier");
    await cashier.goto("/cashier/shift");
    const form = cashier.getByTestId("handover-form");
    await choose(cashier, t("cashier:handover.to"), t("cashier:handover.destination.supervisor"));
    await form.getByLabel(t("cashier:handover.amount")).fill("1000");
    await choose(cashier, t("cashier:handover.toUser"), "Hala Ibrahim");
    await form.getByRole("button", { name: t("cashier:handover.submit") }).click();
    const transit = cashier.getByTestId("handovers-in-transit");
    await expect(transit).toContainText("Hala Ibrahim");
    await expect(cashier.getByTestId("shift-report")).toContainText(t("cashier:handover.state.inTransit"));

    const sup = await pageAs(browser, "cashsup");
    await sup.goto("/cashier/review");
    const incoming = sup.getByTestId("incoming-handovers");
    await expect(incoming).toContainText(sdg("1000.00"));
    await incoming
      .getByRole("button", { name: /Receive handover/ })
      .first()
      .click();
    await expect(incoming).toHaveCount(0);

    await cashier.reload();
    await expect(cashier.getByTestId("handovers-in-transit")).toHaveCount(0);
    await expect(cashier.getByTestId("shift-report")).toContainText(
      t("cashier:handover.state.received", { name: "Hala Ibrahim" }),
    );
    await cashier.context().close();
    await sup.context().close();
  });

  test("a receipt is checked by its code; a rejected transfer is marked not valid", async ({ browser }) => {
    const { patient } = await createPatient();
    const { visit } = await createVisit({ patient });
    await approveInvoice({ visit });
    await noShift("cashier");
    const paid = await pay({
      visit,
      method: "bank_transfer",
      sender_name: "Osman Ali",
    });

    const sup = await pageAs(browser, "cashsup");
    await sup.goto(`/cashier/receipt-check?q=${encodeURIComponent(paid.payment.number)}`);
    await expect(sup.getByTestId("receipt-check-result")).toHaveAttribute("data-standing", "pending");
    // A forged amount on the code does not match the payment.
    await sup.getByLabel(t("cashier:receiptCheck.label")).fill(`${paid.payment.number}|1.00|2020-01-01`);
    await sup.getByTestId("receipt-check-submit").click();
    await expect(sup.getByTestId("receipt-check-result")).toHaveAttribute("data-standing", "mismatch");

    // The supervisor rejects the transfer (reversed in the cashier's open shift): the receipt
    // no longer stands.
    await sup.goto("/cashier/transfers");
    const row = sup.locator("tr").filter({ hasText: paid.payment.number });
    await row.getByRole("button", { name: tr("en", "table.rowActions") }).click();
    await sup.getByRole("menuitem", { name: t("cashier:transfers.reject") }).click();
    await choose(sup, tr("en", "reason.code"), "Money not received");
    await sup
      .getByRole("dialog")
      .getByRole("button", { name: t("cashier:transfers.reject") })
      .click();
    await expect(sup.getByTestId("rejection-outcome")).toBeVisible();
    await sup.goto(`/cashier/receipt-check?q=${encodeURIComponent(paid.payment.number)}`);
    await expect(sup.getByTestId("receipt-check-result")).toHaveAttribute("data-standing", "rejected");
    await sup.goto(`/cashier/receipts/${String(paid.payment.id)}`);
    await expect(sup.getByTestId("receipt-invalid")).toBeVisible();
    await sup.context().close();
  });

  test("printing prints the shift report alone and leaves other screens intact", async ({ browser }) => {
    await noShift("cashier");
    const shift = await openShift({ opening_float: "100" });
    const page = await pageAs(browser, "cashsup");
    await page.goto(`/cashier/shifts/${String(shift.id)}`);
    await expect(page.getByTestId("shift-report")).toBeVisible();
    await page.emulateMedia({ media: "print" });
    await expect(page.getByTestId("shift-report")).toBeVisible();
    await expect(page.locator("[data-slot=cashier-nav]")).toBeHidden();
    await expect(page.locator("#main h1")).toBeHidden();

    // A screen without a printable document prints as it is (not a blank page).
    await page.goto("/cashier/review");
    await expect(page.locator("#main h1")).toBeVisible();
    await page.emulateMedia({ media: "screen" });
    await page.context().close();
  });
});
