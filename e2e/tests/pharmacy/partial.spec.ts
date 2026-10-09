/**
 * Only paid prescriptions reach the pharmacy (invariant 1), and a line can be given in part
 * with the rest kept open (FEATURES 8.3, FLOW 6).
 */
import { expect, test } from "@playwright/test";

import { disposeApiClients } from "../../helpers";
import { openDispense, pageAs, prescription, t } from "./kit";

test.describe("@pharmacy queue and partial dispense", () => {
  test.describe.configure({ timeout: 150_000 });
  test.afterAll(disposeApiClients);

  test("an unpaid prescription is not in the queue", async ({ browser }) => {
    // Invoiced at the cashier but not paid: nothing to dispense yet.
    const visitNumber = await prescription("DRG-PARA500", 10, false);
    const page = await pageAs(browser, "pharmacist");
    await page.goto("/pharmacy");
    const scan = page.getByTestId("queue-scan");
    await scan.fill(visitNumber);
    await scan.press("Enter");
    await expect(page.getByText(t("pharmacy:queue.noMatch"))).toBeVisible();
    await expect(page.getByText(t("pharmacy:queue.noMatchHint"))).toBeVisible();
    await expect(page.getByTestId("dispense-dialog")).toHaveCount(0);
    await page.context().close();
  });

  test("partial dispense keeps the rest open", async ({ browser }) => {
    const visitNumber = await prescription("DRG-METRO500", 10);
    const page = await pageAs(browser, "pharmacist");
    const dialog = await openDispense(page, visitNumber);

    await dialog.getByTestId("dispense-qty").fill("4");
    // Fewer than ordered: the pharmacist decides what happens to the rest.
    await expect(dialog.getByText(t("pharmacy:dispense.partialTitle", { rest: "6" }))).toBeVisible();
    await dialog.getByTestId("remainder-defer").click();
    await dialog.getByTestId("dispense-submit").click();
    await expect(dialog.getByTestId("dispense-done")).toBeVisible();
    await dialog.getByTestId("dispense-close").click();

    // Still in the queue with the six tablets left, marked as partly given.
    await page.getByTestId("queue-scan").fill(visitNumber);
    const card = page.locator(`[data-testid="queue-visit"][data-visit-number="${visitNumber}"]`);
    await expect(card).toBeVisible();
    await expect(card).toContainText(t("pharmacy:queue.started"));
    await expect(card).toContainText("6");

    // The rest is given later from the same line.
    await card.getByTestId("queue-dispense").click();
    const again = page.getByTestId("dispense-dialog");
    await expect(again.getByTestId("dispense-qty")).toHaveValue("6");
    await again.getByTestId("dispense-submit").click();
    await expect(again.getByTestId("dispense-done")).toBeVisible();
    await page.context().close();
  });
});
