/**
 * The portal home on a phone: what needs action comes first (money to pay with how to pay,
 * results outside the normal range), each result says its status in words, and the last card
 * is never hidden under the fixed tab bar.
 */
import { expect, test } from "@playwright/test";

import { expectNoHorizontalScroll } from "../../helpers";
import { phonePage, screensPatient, signInPortal, t } from "./kit";

interface Summary {
  balance: { outstanding: string };
  latest_results: { abnormal: boolean }[];
}

test.describe("@portal home", () => {
  test.describe.configure({ timeout: 120_000 });

  test("what needs action leads, and the last card clears the tab bar", async ({
    browser,
  }) => {
    const who = await screensPatient();
    const page = await phonePage(browser);
    await signInPortal(page, who);
    const summary = (await (
      await page.context().request.get("/api/portal/summary")
    ).json()) as Summary;
    await page.goto("/portal/home");

    const action = page.getByTestId("home-action");
    await expect(action).toBeVisible();
    const owes = Number(summary.balance.outstanding) !== 0;
    const abnormal = summary.latest_results.some((r) => r.abnormal);
    if (owes) {
      await expect(action.getByTestId("home-pay")).toBeVisible();
      await expect(action).toContainText(t("portal:home.howToPay"));
    }
    if (!owes && !abnormal)
      await expect(page.getByTestId("home-nothing")).toBeVisible();
    // The action section comes before the appointment card in reading order.
    const order = await page.evaluate(() => {
      const a = document.querySelector('[data-testid="home-action"]');
      const b = document.querySelector('[data-testid="home-appointment"]');
      return a && b
        ? a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING
        : 0;
    });
    expect(order).toBeTruthy();

    // Every listed result names its status.
    const statuses = page
      .getByTestId("home-results")
      .getByTestId("result-status");
    const count = await statuses.count();
    for (let i = 0; i < count; i++)
      await expect(statuses.nth(i)).not.toBeEmpty();

    await expectNoHorizontalScroll(page);
    await page.evaluate(() => {
      window.scrollTo(0, document.documentElement.scrollHeight);
    });
    const balance = await page.getByTestId("home-balance").boundingBox();
    const nav = await page.locator('[data-slot="portal-nav"]').boundingBox();
    if (!balance || !nav) throw new Error("balance card or tab bar missing");
    expect(balance.y + balance.height).toBeLessThanOrEqual(nav.y);
  });
});
