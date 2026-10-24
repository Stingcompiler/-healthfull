/**
 * The point-of-service pieces of Design Reference 2.2 (docs/DECISIONS.md D-0013, D-0014): density
 * per area, the status bar, the F-key shortcuts and the two connection notices.
 */
import { expect, test } from "@playwright/test";

import { ADMIN_STATE } from "../fixtures/state";
import { setPrefs } from "../helpers";

test.describe("@desk density, status bar and shortcuts", () => {
  test.use({ storageState: ADMIN_STATE, viewport: { width: 1280, height: 800 } });

  test("the cashier runs compact with a status bar; the dashboard does not", async ({ page }) => {
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/");
    await expect(page.locator("#main h1")).toBeVisible();
    await expect(page.locator('#main [data-density="compact"]')).toHaveCount(0);

    await page.goto("/cashier");
    await expect(page.locator("#main h1")).toBeVisible();
    await expect(page.locator('#main [data-density="compact"]')).toHaveCount(1);
    const bar = page.getByTestId("pos-status-bar");
    await expect(bar).toBeVisible();
    await expect(bar).toContainText("Operator");
    await expect(page.getByTestId("pos-connection")).toHaveAttribute("data-state", "connected");
    // No horizontal scroll with the bar in place.
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });

  test("F10 opens refunds from the cashier and dispense returns from the pharmacy", async ({ page }) => {
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/cashier");
    await expect(page.locator("#main h1")).toBeVisible();
    await page.keyboard.press("F10");
    await expect(page).toHaveURL(/\/cashier\/refunds/);

    await page.goto("/pharmacy");
    await expect(page.getByTestId("queue-scan")).toBeVisible();
    await page.getByTestId("queue-scan").blur();
    await page.keyboard.press("F2");
    await expect(page.getByTestId("queue-scan")).toBeFocused();
    await page.keyboard.press("F10");
    await expect(page).toHaveURL(/\/pharmacy\/returns/);
  });

  test("the shortcut list opens with ? and documents F10", async ({ page }) => {
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/pharmacy");
    await expect(page.getByTestId("queue-scan")).toBeVisible();
    await page.getByTestId("queue-scan").blur();
    await page.keyboard.press("Shift+/");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("F10");
    await expect(dialog).toContainText("F2");
  });
});

test.describe("@desk connection notices", () => {
  test.use({ storageState: ADMIN_STATE, viewport: { width: 1280, height: 800 } });

  test("unreachable when the link drops, restored when it returns, never blocking", async ({ page, context }) => {
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/");
    await expect(page.locator("#main h1")).toBeVisible();
    await expect(page.getByTestId("connection-banner")).toHaveCount(0);

    await context.setOffline(true);
    const banner = page.getByTestId("connection-banner");
    await expect(banner).toHaveAttribute("data-state", "unreachable");
    await expect(banner).toContainText("Can't reach the server");
    // Not a dialog: the page underneath stays usable.
    await expect(page.getByRole("dialog")).toHaveCount(0);

    await context.setOffline(false);
    await expect(banner).toHaveAttribute("data-state", "restored");
    await expect(banner).toContainText("Connection restored");
    await expect(banner).toHaveCount(0, { timeout: 15_000 });
  });
});
