/**
 * Goods receipt and FEFO dispensing (FEATURES 8.2, 8.3, 8.5; invariants 1 and 5): the
 * pharmacist receives two batches of ibuprofen, one expiring in two days and one next year;
 * a paid prescription is then dispensed from the batch that expires first, and taking another
 * batch needs a reason.
 */
import { expect, test } from "@playwright/test";

import { disposeApiClients, snap } from "../../helpers";
import { choose, dayFromNow, openDispense, pageAs, prescription, stamp, t } from "./kit";

const ITEM = "DRG-IBU400";

test.describe("@pharmacy receive and dispense", () => {
  test.describe.configure({ mode: "serial", timeout: 150_000 });
  test.afterAll(disposeApiClients);

  const suffix = stamp();
  const early = `E2E-E-${suffix}`;
  const late = `E2E-L-${suffix}`;

  test("receive goods with two batches", async ({ browser }) => {
    const page = await pageAs(browser, "pharmacist");
    await page.goto("/pharmacy/receipts");
    await page.getByTestId("receipt-new").click();
    const dialog = page.getByTestId("receipt-dialog");
    await choose(dialog, t("pharmacy:receipts.fields.supplier"), "Medical Supply Co. (test)");
    await choose(dialog, t("pharmacy:receipts.fields.store"), "Outpatient pharmacy");
    await dialog.getByTestId("receipt-invoice-no").fill(`SINV-${suffix}`);

    const lines = dialog.getByTestId("receipt-line");
    const fillLine = async (index: number, batch: string, expiry: string, qty: string, cost: string) => {
      const line = lines.nth(index);
      await line.getByTestId("receipt-item").fill("Ibuprofen");
      await line.getByTestId("receipt-item-results").getByRole("button").first().click();
      await expect(line.getByTestId("receipt-item-selected")).toContainText("Ibuprofen");
      await line.getByTestId("receipt-batch").fill(batch);
      await line.getByTestId("receipt-expiry").fill(expiry);
      await line.getByTestId("receipt-qty").fill(qty);
      await line.getByTestId("receipt-cost").fill(cost);
    };
    await fillLine(0, early, dayFromNow(2), "5", "90");
    await dialog.getByTestId("receipt-add-line").click();
    await fillLine(1, late, dayFromNow(400), "50", "95");
    await dialog.getByTestId("receipt-save").click();

    // The draft opens; nothing is in stock until it is posted.
    const detail = page.getByTestId("receipt-detail");
    await expect(detail).toBeVisible();
    await expect(detail.locator('[data-status="draft"]')).toBeVisible();
    await expect(detail).toContainText(early);
    await expect(detail).toContainText(late);
    await detail.getByTestId("receipt-post").click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: t("pharmacy:receipts.post") })
      .click();
    await expect(detail.locator('[data-status="posted"]')).toBeVisible();
    await page.context().close();
  });

  test("dispense picks the earliest expiry", async ({ browser }) => {
    const visitNumber = await prescription(ITEM, 5);
    const page = await pageAs(browser, "pharmacist");
    const dialog = await openDispense(page, visitNumber);

    // The batch that expires first is suggested for every unit.
    const suggested = dialog.locator('[data-testid="dispense-batch"][data-suggested="true"]');
    await expect(suggested).toHaveCount(1);
    await expect(suggested).toHaveAttribute("data-batch-no", early);
    await snap(page, "pharmacy-dispense-dialog");
    await dialog.getByTestId("dispense-submit").click();

    const done = dialog.getByTestId("dispense-done");
    await expect(done).toBeVisible();
    await expect(done.getByTestId("dispensed-batch")).toHaveText([early]);
    await done.getByTestId("dispense-close").click();

    // Fully given: the visit leaves the queue.
    await page.getByTestId("queue-scan").fill(visitNumber);
    await expect(page.getByText(t("pharmacy:queue.noMatch"))).toBeVisible();
    await page.context().close();
  });

  test("another batch needs a reason", async ({ browser }) => {
    const visitNumber = await prescription(ITEM, 2);
    const page = await pageAs(browser, "pharmacist");
    const dialog = await openDispense(page, visitNumber);

    await dialog.getByTestId("dispense-override").click();
    const batches = dialog.getByTestId("dispense-batch");
    const count = await batches.count();
    for (let i = 0; i < count; i += 1) {
      const row = batches.nth(i);
      const isLate = (await row.getAttribute("data-batch-no")) === late;
      await row.getByTestId("dispense-pick").fill(isLate ? "2" : "0");
    }
    // No reason: refused on the line, nothing leaves the shelf.
    await dialog.getByTestId("dispense-submit").click();
    await expect(dialog.getByTestId("dispense-line-error")).toHaveText(t("pharmacy:dispense.reasonRequired"));

    await choose(dialog, t("pharmacy:dispense.overrideReason"), /Different (batch|lot) chosen/);
    await dialog.getByTestId("dispense-reason-note").fill("Patient travels for a year");
    await dialog.getByTestId("dispense-submit").click();
    const done = dialog.getByTestId("dispense-done");
    await expect(done).toBeVisible();
    await expect(done.getByTestId("dispensed-batch")).toHaveText([late]);
    await expect(done).toContainText(t("pharmacy:dispense.overridden"));
    await page.context().close();
  });
});
