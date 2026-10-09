/**
 * Bank transfers (FEATURES 6.2-6.4, 6.8): pending money settles the lines but the shift report
 * shows it as pending, never as collected. After the shift closes a supervisor confirms one
 * transfer and rejects another: the rejection's reversal lands in the supervisor's own open
 * shift, the closed shift's report does not change, and the invoice is owed again.
 */
import { expect, test } from "@playwright/test";

import {
  apiAs,
  approveInvoice,
  createPatient,
  createVisit,
  disposeApiClients,
  openShift,
  pay,
  tr,
} from "../../helpers";
import { choose, lineState, noShift, openVisit, pageAs, sdg, t } from "./kit";

interface ShiftReport {
  shift: { id: number; number: string; status: string };
  collection: { bank_pending: string; confirmed_total: string };
  pending: { number: string }[];
  late_reversals: string;
}

test.describe("@cashier transfers", () => {
  test.describe.configure({ timeout: 180_000 });
  test.afterAll(disposeApiClients);

  test("pending settles lines, shows pending; confirm one, reject one after close", async ({ browser }) => {
    const pa = (await createPatient()).patient;
    const a = await createVisit({ patient: pa });
    const b = await createVisit({ patient: (await createPatient()).patient });
    const invA = (await approveInvoice({ visit: a.visit })).invoice;
    const invB = (await approveInvoice({ visit: b.visit })).invoice;
    await noShift("cashier");
    await openShift({ opening_float: "0" });
    const refA = `TA${String(Date.now())}`;

    // The cashier takes visit A's 15,000 by bank transfer at the desk.
    const cashier = await pageAs(browser, "cashier");
    await openVisit(cashier, pa.file_no, a.visit.number);
    const panel = cashier.getByTestId("payment-panel");
    await panel.getByTestId("method-bank_transfer").click();
    await choose(cashier, t("cashier:payment.bank"), "Bank of Khartoum (Bankak)");
    await panel.getByLabel(t("cashier:payment.reference")).fill(refA);
    await panel.getByTestId("take-payment").click();
    const done = panel.getByTestId("payment-done");
    await expect(done.locator('[data-status="pending_verification"]')).toBeVisible();
    // Pending money settles the lines: the service proceeds.
    await expect(cashier.getByTestId("approved-invoice").locator(lineState("paid"))).toHaveCount(1);

    // Visit B is paid by transfer too (through the API).
    const paidB = await pay({ invoice: invB, method: "bank_transfer" });
    expect(paidB.payment.verification).toBe("pending");

    // The shift report keeps both apart from collected money; then the cashier closes.
    await cashier.goto("/cashier/shift");
    await expect(cashier.getByTestId("report-bank-pending")).toContainText(sdg("30000.00"));
    await expect(cashier.getByTestId("report-confirmed-total")).toContainText(sdg("0.00"));
    await expect(cashier.getByTestId("report-pending").locator("li")).toHaveCount(2);
    await cashier.getByLabel(t("cashier:close.counted")).fill("0");
    await cashier.getByTestId("close-shift").click();
    await cashier.getByRole("alertdialog").getByRole("button", { name: t("cashier:close.submit") }).click();
    await expect(cashier.getByTestId("shift-report")).toHaveAttribute("data-frozen", "true");
    const current = await (await apiAs("cashier")).get<{ report: ShiftReport | null }>("/api/payments/shifts/current");
    expect(current.report).toBeNull();

    // The supervisor works from their own open shift.
    const supShift = await openShift({ as: "cashsup", if_open: "reuse" });
    const sup = await pageAs(browser, "cashsup");
    await sup.goto("/cashier/transfers");
    const rowA = sup.locator("tr").filter({ hasText: refA });
    const rowB = sup.locator("tr").filter({ hasText: paidB.payment.reference });
    await expect(rowA).toBeVisible();
    await expect(rowB).toBeVisible();

    // Confirm A, saying what was checked.
    await rowA.getByRole("button", { name: tr("en", "table.rowActions") }).click();
    await sup.getByRole("menuitem", { name: t("cashier:transfers.confirm") }).click();
    const confirmDialog = sup.getByTestId("confirm-transfer-dialog");
    await confirmDialog.getByLabel(t("cashier:transfers.checked")).fill("Seen in the Bankak statement");
    await confirmDialog.getByRole("button", { name: t("cashier:transfers.confirm") }).click();
    await expect(rowA).toHaveCount(0);

    // Reject B: its shift is closed, so the reversal lands in the supervisor's shift.
    await rowB.getByRole("button", { name: tr("en", "table.rowActions") }).click();
    await sup.getByRole("menuitem", { name: t("cashier:transfers.reject") }).click();
    await choose(sup, tr("en", "reason.code"), "Money not received");
    await sup.getByRole("dialog").getByRole("button", { name: t("cashier:transfers.reject") }).click();
    await expect(sup.getByTestId("rejection-outcome")).toContainText(supShift.number);
    await expect(rowB).toHaveCount(0);

    // Invoice B is owed again; the closed shift's report did not change.
    const api = await apiAs("cashsup");
    const billingB = await api.get<{ invoices: { outstanding: string; lines: { state: string }[] }[] }>(
      `/api/billing/visits/${String(b.visit.id)}`,
    );
    expect(billingB.invoices[0]?.outstanding).toBe("15000.00");
    expect(billingB.invoices[0]?.lines.map((l) => l.state)).toEqual(["invoiced"]);
    const closed = await api.get<ShiftReport>(`/api/payments/shifts/${String(paidB.shift.id)}`);
    expect(closed.shift.status).toBe("closed");
    expect(closed.collection.bank_pending).toBe("30000.00");
    expect(closed.pending).toHaveLength(2);
    expect(closed.pending.map((p) => p.number)).toContain(paidB.payment.number);

    // The supervisor's open shift shows the late reversal.
    await sup.goto("/cashier/shift");
    await expect(sup.getByTestId("report-late-reversals")).toContainText(sdg("15000.00"));
    expect(invA.outstanding).toBe("15000.00");
    await cashier.context().close();
    await sup.context().close();
  });
});
