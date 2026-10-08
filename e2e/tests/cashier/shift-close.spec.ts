/**
 * Shift close (FEATURES 7.2, 7.5): a counted cash that differs from the expected cash needs a
 * variance reason; the report freezes, and a manager (never the cashier) signs it off.
 */
import { expect, test } from "@playwright/test";

import { disposeApiClients, openShift, tr } from "../../helpers";
import { choose, noShift, pageAs, sdg, t } from "./kit";

test.describe("@cashier shift close", () => {
  test.describe.configure({ timeout: 120_000 });
  test.afterAll(disposeApiClients);

  test("a variance needs an explanation, then the manager signs off", async ({ browser }) => {
    await noShift("cashier");
    const shift = await openShift({ opening_float: "1000" });

    const page = await pageAs(browser, "cashier");
    await page.goto("/cashier/shift");
    await expect(page.getByTestId("shift-report")).toHaveAttribute("data-frozen", "false");
    await page.getByLabel(t("cashier:close.counted")).fill("900");
    // The live hint shows the shortfall before anything is sent.
    await expect(page.getByTestId("close-shift-form")).toContainText(sdg("100.00"));
    await page.getByTestId("close-shift").click();
    const confirm = page.getByRole("alertdialog");
    await confirm.getByRole("button", { name: t("cashier:close.submit") }).click();
    // Refused by the server without a reason: the shift stays open.
    await expect(confirm.getByRole("alert")).toContainText(
      tr("en", "errors:VARIANCE_EXPLANATION_REQUIRED").split("{{")[0] ?? "",
    );
    await confirm.getByRole("button", { name: tr("en", "actions.cancel") }).click();

    await choose(page, t("cashier:close.reason"), "Counting error");
    await page.getByTestId("close-shift-form").getByLabel(tr("en", "reason.note")).fill("Coins miscounted");
    await page.getByTestId("close-shift").click();
    await page.getByRole("alertdialog").getByRole("button", { name: t("cashier:close.submit") }).click();
    await expect(page.getByTestId("shift-report")).toHaveAttribute("data-frozen", "true");
    await expect(page.getByTestId("report-variance")).toContainText(sdg("100.00"));
    await page.context().close();

    // The manager reviews it from the queue.
    const manager = await pageAs(browser, "manager");
    await manager.goto("/cashier/review");
    const row = manager.locator("tr").filter({ hasText: shift.number });
    await expect(row).toBeVisible();
    await row.getByRole("button").first().click();
    await expect(manager).toHaveURL(new RegExp(`/cashier/shifts/${String(shift.id)}$`));
    await expect(manager.getByTestId("shift-report")).toContainText("Counting error");
    await manager.getByLabel(tr("en", "reason.note")).fill("Variance explained");
    await manager.getByTestId("sign-off").click();
    await expect(manager.getByTestId("review-form")).toHaveCount(0);
    await expect(manager.getByTestId("shift-report")).toContainText(t("cashier:review.outcome.approved"));

    await manager.goto("/cashier/review");
    await expect(manager.locator("tr").filter({ hasText: shift.number })).toHaveCount(0);
    await manager.context().close();
  });
});
