/**
 * A transfer reference is unique per bank (FEATURES 6.2): a second use is refused, then
 * accepted with a reason and a supervisor approving at the cashier's desk (ADR 0007). The
 * money still goes into the cashier's own shift and the override is recorded on the payment.
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
import { E2E_PASSWORD } from "../../fixtures/users";
import { choose, noShift, openVisit, pageAs, t } from "./kit";

test.describe("@cashier duplicate reference", () => {
  test.describe.configure({ timeout: 150_000 });
  test.afterAll(disposeApiClients);

  test("blocked, then overridden by a supervisor at the desk", async ({ browser }) => {
    const first = await createVisit({ patient: (await createPatient()).patient });
    const pb = (await createPatient()).patient;
    const second = await createVisit({ patient: pb });
    const invA = (await approveInvoice({ visit: first.visit })).invoice;
    await approveInvoice({ visit: second.visit });
    await noShift("cashier");
    await openShift({ opening_float: "0" });
    const reference = `DUP${String(Date.now())}`;
    const original = await pay({ invoice: invA, method: "bank_transfer", bank: "BOK", reference });

    const page = await pageAs(browser, "cashier");
    await openVisit(page, pb.file_no, second.visit.number);
    const panel = page.getByTestId("payment-panel");
    await panel.getByTestId("method-bank_transfer").click();
    await choose(page, t("cashier:payment.bank"), "Bank of Khartoum (Bankak)");
    // Same reference, written differently: normalization still finds the duplicate.
    await panel.getByLabel(t("cashier:payment.reference")).fill(` ${reference.toLowerCase()} `);
    await panel.getByTestId("take-payment").click();
    await expect(panel.getByRole("alert")).toContainText(tr("en", "errors:DUPLICATE_REFERENCE").slice(0, 20));
    const override = panel.getByTestId("override");
    await expect(override).toBeVisible();

    // A wrong supervisor password is refused without ending the cashier's session.
    await choose(page, tr("en", "reason.code"), "Duplicate reference verified");
    await override.getByRole("switch", { name: t("cashier:approver.toggle") }).click();
    await override.getByLabel(t("cashier:approver.username")).fill("cashsup");
    await override.getByLabel(t("cashier:approver.password")).fill("not-the-password");
    await panel.getByTestId("take-payment").click();
    await expect(panel.getByRole("alert")).toContainText(tr("en", "errors:APPROVER_INVALID"));

    await override.getByLabel(t("cashier:approver.password")).fill(E2E_PASSWORD);
    await panel.getByTestId("take-payment").click();
    await expect(panel.getByTestId("payment-done").locator('[data-status="pending_verification"]')).toBeVisible();

    // Recorded on the payment: flagged, linked to the first use, approved by the supervisor.
    const api = await apiAs("cashier");
    const billing = await api.get<{ invoices: { payments: { payment_id: number }[] }[] }>(
      `/api/billing/visits/${String(second.visit.id)}`,
    );
    const paymentId = billing.invoices[0]?.payments[0]?.payment_id;
    expect(paymentId).toBeDefined();
    const payment = await api.get<{
      duplicate_override: boolean;
      duplicate_of_number: string | null;
      override_by: { username: string } | null;
      override_reason: { code: string } | null;
      shift_id: number;
    }>(`/api/payments/payments/${String(paymentId)}`);
    expect(payment.duplicate_override).toBe(true);
    expect(payment.duplicate_of_number).toBe(original.payment.number);
    expect(payment.override_by?.username).toBe("cashsup");
    expect(payment.override_reason?.code).toBe("DUPLICATE_VERIFIED");
    expect(payment.shift_id).toBe(original.shift.id);
    await page.context().close();
  });
});
