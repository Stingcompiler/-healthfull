/**
 * Refund after a credit note (FEATURES 5.11, 6.7, FLOW 8): the cashier drafts a credit note
 * on an approved and paid invoice, a supervisor approves it (the released money opens a refund
 * request in the supervisor's name, ADR 0009), so a second person (the accountant) approves the
 * refund, and the cashier pays it in cash from their own shift.
 */
import { expect, test } from "@playwright/test";

import { disposeApiClients, paidVisit, tr } from "../../helpers";
import { choose, noShift, openVisit, pageAs, sdg, t } from "./kit";

test.describe("@cashier refund", () => {
  test.describe.configure({ timeout: 150_000 });
  test.afterAll(disposeApiClients);

  test("credit note, supervisor approval, accountant refund approval, cash refund", async ({ browser }) => {
    await noShift("cashier");
    // A consultation invoiced and paid in cash (15,000) in the cashier's new shift.
    const paid = await paidVisit();
    if (!paid.invoice || !paid.shift) throw new Error("paidVisit() returned no invoice or shift");

    const cashier = await pageAs(browser, "cashier");
    await openVisit(cashier, paid.patient.file_no, paid.visit.number);
    const invoice = cashier.getByTestId("approved-invoice");
    await invoice.getByTestId("open-credit-note").click();
    const dialog = cashier.getByTestId("credit-note-dialog");
    const qty = dialog.locator("[data-testid^=credit-qty-]").first();
    await choose(cashier, tr("en", "reason.code"), "Service cancelled");
    // No unit chosen: a validation message under the lines, not a system error.
    await dialog.getByRole("button", { name: t("cashier:creditNote.submit") }).click();
    await expect(dialog.getByTestId("credit-lines-error")).toHaveText(t("cashier:creditNote.chooseLines"));
    // More than the line holds is refused on the line itself.
    await qty.fill("5");
    await dialog.getByRole("button", { name: t("cashier:creditNote.submit") }).click();
    await expect(dialog.getByText(t("cashier:creditNote.qtyInvalid", { max: "1" }))).toBeVisible();
    // Arabic-Indic digits are read as the number they are.
    await qty.fill("١");
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

    // The supervisor asked for the refund, so a second person (the accountant) approves it.
    const accountant = await pageAs(browser, "accountant");
    await accountant.goto("/cashier/refunds");
    const refundRow = accountant.locator("tr").filter({ hasText: paid.patient.full_name_en });
    await expect(refundRow).toBeVisible();
    await expect(refundRow).toContainText(sdg("15000.00"));
    await expect(refundRow).toContainText("Hala Ibrahim");
    await refundRow.getByRole("button", { name: tr("en", "table.rowActions") }).click();
    await accountant.getByRole("menuitem", { name: t("cashier:refunds.approve") }).click();
    await accountant.getByRole("dialog").getByRole("button", { name: t("cashier:refunds.approve") }).click();
    await expect(refundRow).toHaveCount(0);
    await accountant.context().close();

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
