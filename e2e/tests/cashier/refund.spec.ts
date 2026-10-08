/**
 * Refund after a credit note (FEATURES 5.11, 6.7, FLOW 8): the cashier drafts a credit note
 * on an approved and paid invoice, a supervisor approves it (the released money opens a refund
 * request), approves the refund, and the cashier pays it in cash from their own shift.
 */
import { expect, test } from "@playwright/test";

import { disposeApiClients, paidVisit, tr } from "../../helpers";
import { choose, noShift, openVisit, pageAs, sdg, t } from "./kit";

test.describe("@cashier refund", () => {
  test.describe.configure({ timeout: 150_000 });
  test.afterAll(disposeApiClients);

  test("credit note, supervisor approval, refund approval, cash refund", async ({ browser }) => {
    await noShift("cashier");
    // A consultation invoiced and paid in cash (15,000) in the cashier's new shift.
    const paid = await paidVisit();
    if (!paid.invoice || !paid.shift) throw new Error("paidVisit() returned no invoice or shift");

    const cashier = await pageAs(browser, "cashier");
    await openVisit(cashier, paid.patient.file_no, paid.visit.number);
    const invoice = cashier.getByTestId("approved-invoice");
    await invoice.getByTestId("open-credit-note").click();
    const dialog = cashier.getByTestId("credit-note-dialog");
    await dialog.locator("input[type=number]").first().fill("1");
    await choose(cashier, tr("en", "reason.code"), "Service cancelled");
    await dialog.getByRole("button", { name: t("cashier:creditNote.submit") }).click();
    await expect(dialog.getByText(t("cashier:creditNote.createdTitle"))).toBeVisible();
    await dialog.getByRole("button", { name: tr("en", "actions.close") }).first().click();

    // The supervisor approves the credit note; a refund request opens for the released money.
    const sup = await pageAs(browser, "cashsup");
    await sup.goto("/cashier/credit-notes");
    const noteRow = sup.locator("tr").filter({ hasText: paid.invoice.number ?? "" });
    await expect(noteRow).toBeVisible();
    await noteRow.getByRole("button", { name: tr("en", "table.rowActions") }).click();
    await sup.getByRole("menuitem", { name: t("cashier:creditNotes.approve") }).click();
    await sup.getByTestId("approve-credit-note").click();
    await expect(noteRow).toHaveCount(0);

    await sup.goto("/cashier/refunds");
    const refundRow = sup.locator("tr").filter({ hasText: paid.patient.full_name_en });
    await expect(refundRow).toBeVisible();
    await expect(refundRow).toContainText(sdg("15000.00"));
    await refundRow.getByRole("button", { name: tr("en", "table.rowActions") }).click();
    await sup.getByRole("menuitem", { name: t("cashier:refunds.approve") }).click();
    await sup.getByRole("dialog").getByRole("button", { name: t("cashier:refunds.approve") }).click();
    await expect(refundRow).toHaveCount(0);

    // The cashier pays it in cash from their open shift.
    await cashier.goto("/cashier/refunds");
    await cashier.getByRole("tab", { name: t("cashier:refunds.status.approved") }).click();
    const payRow = cashier.locator("tr").filter({ hasText: paid.patient.full_name_en });
    await payRow.getByRole("button", { name: tr("en", "table.rowActions") }).click();
    await cashier.getByRole("menuitem", { name: t("cashier:refunds.pay") }).click();
    await cashier.getByRole("alertdialog").getByRole("button", { name: t("cashier:refunds.pay") }).click();
    await expect(payRow).toHaveCount(0);

    // The refund shows in the shift report and leaves the drawer.
    await cashier.goto("/cashier/shift");
    await expect(cashier.getByTestId("shift-report")).toContainText(t("cashier:report.refundsPaid"));
    await expect(cashier.getByTestId("shift-report")).toContainText(sdg("15000.00"));
    await cashier.context().close();
    await sup.context().close();
  });
});
