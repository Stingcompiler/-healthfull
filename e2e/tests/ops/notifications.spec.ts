/**
 * In-app notifications (FEATURES 0.13): the bell shows the unread count, lists the alerts in
 * the user's language, opening one marks it read and goes to the screen that resolves it, and
 * "mark all read" empties the badge. Phone and desktop widths. `make e2e E2E_GREP=@ops`.
 */
import { expect, test } from "@playwright/test";

import { ANONYMOUS_STATE } from "../../fixtures/state";
import { expectNoHorizontalScroll, fixture, login, setPrefs, snap, tr, type Lang } from "../../helpers";

test.describe.configure({ timeout: 120_000 });
test.use({ storageState: ANONYMOUS_STATE });

const CASES = [
  { width: 1280, height: 800, lang: "en" as Lang },
  { width: 375, height: 812, lang: "ar" as Lang },
];

for (const viewport of CASES) {
  test.describe(`@ops notifications ${String(viewport.width)}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    test(`appear, open and are marked read (${viewport.lang})`, async ({ page }) => {
      const lang = viewport.lang;
      const made = await fixture<{ unread: number }>("ops_notifications", {
        user: "manager",
      });
      expect(made.unread).toBe(3);
      await login(page, "manager");
      await setPrefs(page, { theme: "light", lang });
      await page.goto("/");

      const bell = page.getByTestId("notifications-bell");
      await expect(page.getByTestId("notifications-badge")).toHaveText("3");
      await bell.click();
      const list = page.getByTestId("notifications-list");
      await expect(list.locator("[data-unread=true]")).toHaveCount(3);
      await expect(list).toContainText(tr(lang, "ops:notifications.kinds.backup_stale", { hours: "36" }));
      await expect(page.getByRole("dialog")).toBeVisible();
      await expectNoHorizontalScroll(page);
      await snap(page, "ops-notifications");

      // Opening the shift alert marks it read and goes to the manager's shift review.
      await list
        .locator("[data-unread=true]")
        .filter({ hasText: tr(lang, "ops:notifications.kinds.shift_review_pending_one", { count: "1" }) })
        .click();
      await expect(page).toHaveURL(/\/cashier\/review$/);
      await expect(page.getByTestId("notifications-badge")).toHaveText("2");

      await bell.click();
      await page.getByRole("button", { name: tr(lang, "ops:notifications.markAll") }).click();
      await expect(page.getByTestId("notifications-badge")).toHaveCount(0);
      await expect(list.locator("[data-unread=true]")).toHaveCount(0);
    });
  });
}
