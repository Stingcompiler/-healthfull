/**
 * Second cashier review (ADR 0008, FEATURES 5.11, 6.3, 6.8, 6.9, 7.3):
 * - the chosen payment method shows as checked, not only to screen readers;
 * - the thermal receipt prints on an 80 mm page and A4 on A4;
 * - a supervisor never confirms a transfer or approves a credit note they made;
 * - a closed shift's transfer cannot be rejected by an accountant with no till (a hint says
 *   who can), and the transfer table fits at 1280 without scrolling sideways;
 * - a desk cancellation before invoicing shows on the shift report.
 */
import { expect, test, type Page } from "@playwright/test";

import {
  apiAs,
  approveInvoice,
  createInvoice,
  createPatient,
  createVisit,
  disposeApiClients,
  openShift,
  orderLines,
  paidVisit,
  pay,
  tr,
} from "../../helpers";
import { noShift, openVisit, pageAs, t } from "./kit";

/** Width and height (pt) of the first page of a PDF rendered by Chromium. */
async function pdfPageSize(page: Page): Promise<[number, number]> {
  const pdf = (await page.pdf({ preferCSSPageSize: true, printBackground: true })).toString("latin1");
  const box = /\/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]/.exec(pdf);
  if (!box) throw new Error("no MediaBox in the printed PDF");
  return [Number(box[1]), Number(box[2])];
}

const MM = 72 / 25.4;

async function rowMenu(page: Page, rowText: string): Promise<void> {
  const row = page.locator("tr").filter({ hasText: rowText });
  await row.getByRole("button", { name: tr("en", "table.rowActions") }).click();
}

test.describe("@cashier second person", () => {
  test.describe.configure({ timeout: 180_000 });
  test.afterAll(disposeApiClients);

  test("the chosen payment method is checked and looks it", async ({ browser }) => {
    const { patient } = await createPatient();
    const { visit } = await createVisit({ patient });
    await approveInvoice({ visit });
    await noShift("cashier");
    await openShift({ opening_float: "0" });
    const page = await pageAs(browser, "cashier");
    await openVisit(page, patient.file_no, visit.number);
    const panel = page.getByTestId("payment-panel");
    const cash = panel.getByTestId("method-cash");
    const transfer = panel.getByTestId("method-bank_transfer");
    await expect(cash).toHaveAttribute("role", "radio");
    await expect(cash).toHaveAttribute("aria-checked", "true");
    await expect(cash).toHaveAttribute("data-state", "checked");
    const background = (el: Element) => getComputedStyle(el).backgroundColor;
    expect(await cash.evaluate(background)).not.toBe(await transfer.evaluate(background));
    await transfer.click();
    await expect(transfer).toHaveAttribute("data-state", "checked");
    await expect(cash).toHaveAttribute("data-state", "unchecked");
    await page.keyboard.press("Alt+1");
    await expect(cash).toHaveAttribute("data-state", "checked");
    await page.context().close();
  });

  test("the thermal receipt prints on an 80 mm page, A4 on A4", async ({ browser }) => {
    await noShift("cashier");
    const paid = await paidVisit();
    if (!paid.payment) throw new Error("paidVisit() returned no payment");
    const page = await pageAs(browser, "cashier");
    await page.goto(`/cashier/receipts/${String(paid.payment.id)}`);
    await expect(page.getByTestId("receipt")).toBeVisible();
    await expect(page.getByTestId("format-thermal")).toHaveAttribute("data-state", "active");
    const [width] = await pdfPageSize(page);
    expect(Math.abs(width - 80 * MM)).toBeLessThan(2);
    await page.getByTestId("format-a4").click();
    const [a4Width, a4Height] = await pdfPageSize(page);
    expect(Math.abs(a4Width - 210 * MM)).toBeLessThan(2);
    expect(Math.abs(a4Height - 297 * MM)).toBeLessThan(2);
    await page.context().close();
  });

  test("supervisors never check their own transfers or credit notes", async ({ browser }) => {
    // The supervisor takes a transfer at the desk from their own shift.
    await openShift({ as: "cashsup", if_open: "reuse" });
    const { patient } = await createPatient();
    const { visit } = await createVisit({ patient });
    await approveInvoice({ visit });
    const own = await pay({ visit, method: "bank_transfer", as: "cashsup" });

    const sup = await pageAs(browser, "cashsup");
    await sup.goto("/cashier/transfers");
    const ownRow = sup.locator("tr").filter({ hasText: own.payment.number });
    await expect(ownRow.getByTestId("transfer-self-recorded")).toBeVisible();
    await rowMenu(sup, own.payment.number);
    await expect(sup.getByRole("menuitem", { name: t("cashier:transfers.reject") })).toBeVisible();
    await expect(sup.getByRole("menuitem", { name: t("cashier:transfers.confirm") })).toHaveCount(0);
    await sup.keyboard.press("Escape");

    // The supervisor drafts a credit note on a paid invoice: someone else approves it.
    await noShift("cashier");
    const paid = await paidVisit();
    if (!paid.invoice) throw new Error("paidVisit() returned no invoice");
    const api = await apiAs("cashsup");
    const detail = await api.get<{ lines: { id: number }[] }>(`/api/billing/invoices/${String(paid.invoice.id)}`);
    const lineId = detail.lines[0]?.id ?? 0;
    await api.post(`/api/billing/invoices/${String(paid.invoice.id)}/credit-notes`, {
      lines: [{ invoice_line_id: lineId, quantity: 1 }],
      reason: "PRICE_ERROR",
    });
    await sup.goto("/cashier/credit-notes");
    const noteRow = sup.locator("tr").filter({ hasText: paid.invoice.number ?? "" });
    await expect(noteRow).toContainText(t("cashier:creditNotes.draft"));
    await expect(noteRow.getByTestId("credit-note-own-draft")).toBeVisible();
    await rowMenu(sup, paid.invoice.number ?? "");
    await expect(sup.getByRole("menuitem", { name: t("cashier:creditNotes.openVisit") })).toBeVisible();
    await expect(sup.getByRole("menuitem", { name: t("cashier:creditNotes.approve") })).toHaveCount(0);
    await sup.context().close();

    const accountant = await pageAs(browser, "accountant");
    await accountant.goto("/cashier/credit-notes");
    await rowMenu(accountant, paid.invoice.number ?? "");
    await expect(
      accountant.getByRole("menuitem", {
        name: t("cashier:creditNotes.approve"),
      }),
    ).toBeVisible();
    await accountant.context().close();
  });

  test("an accountant cannot reject a closed shift's transfer and is told who can", async ({ browser }) => {
    const { patient } = await createPatient();
    const { visit } = await createVisit({ patient });
    await approveInvoice({ visit });
    await noShift("cashier");
    const late = await pay({
      visit,
      method: "bank_transfer",
      sender_name: "Osman Ali",
    });
    await noShift("cashier");

    const accountant = await pageAs(browser, "accountant");
    await accountant.goto("/cashier/transfers");
    const row = accountant.locator("tr").filter({ hasText: late.payment.number });
    await expect(row).toContainText(t("cashier:shift.status.closed"));
    await expect(accountant.getByTestId("reject-needs-shift")).toContainText(t("cashier:transfers.needsSupervisor"));
    await rowMenu(accountant, late.payment.number);
    await expect(
      accountant.getByRole("menuitem", {
        name: t("cashier:transfers.rejectBlocked"),
      }),
    ).toHaveAttribute("aria-disabled", "true");
    await accountant.keyboard.press("Escape");
    // At 1280 the table fits its card: nothing scrolls sideways under the sticky actions.
    const overflow = await accountant
      .locator('[data-slot="data-table"][data-mode="table"] [data-slot="table-container"]')
      .evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await accountant.context().close();
  });

  test("a line cancelled at the desk shows on the shift report", async ({ browser }) => {
    const { patient } = await createPatient();
    const { visit } = await createVisit({ patient });
    await orderLines({ visit, items: [{ service: "LAB-CBC" }] });
    await noShift("cashier");
    await openShift({ opening_float: "0" });
    const draft = await createInvoice({ visit });
    const api = await apiAs("cashier");
    const detail = await api.get<{ lines: { id: number }[] }>(`/api/billing/invoices/${String(draft.invoice.id)}`);
    const last = detail.lines[detail.lines.length - 1]?.id ?? 0;
    await api.post(`/api/billing/invoices/${String(draft.invoice.id)}/lines/${String(last)}/cancel`, {
      reason: "PATIENT_REFUSED",
    });

    const page = await pageAs(browser, "cashier");
    await page.goto("/cashier/shift");
    const cancelled = page.getByTestId("report-line-cancellations");
    await expect(cancelled).toContainText("Patient refused");
    await expect(cancelled).toContainText(t("cashier:report.lineCount_one", { count: "1" }));
    await page.context().close();
  });
});
