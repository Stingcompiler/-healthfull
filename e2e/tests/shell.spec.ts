/**
 * App shell layout guards that the per-route matrix cannot see.
 */
import { expect, test } from "@playwright/test";

import { ADMIN_STATE } from "../fixtures/state";
import { LANGS, setPrefs } from "../helpers";

/**
 * The full sidebar (admin: every module) must fit common clinic desktop screens without
 * scrolling, so the last group (Administration) is never hidden below the fold.
 */
test.describe("@responsive sidebar fits desktop screens", () => {
  test.use({ storageState: ADMIN_STATE });

  for (const size of [
    { width: 1280, height: 800 },
    { width: 1366, height: 768 },
  ]) {
    for (const lang of LANGS) {
      test(`${String(size.width)}x${String(size.height)} ${lang}`, async ({ page }) => {
        await page.setViewportSize(size);
        await setPrefs(page, { theme: "light", lang });
        await page.goto("/");
        const nav = page.locator('[data-slot="app-sidebar"] nav');
        await expect(nav.getByTestId("nav-admin")).toBeVisible();
        await page.evaluate(() => document.fonts.ready.then(() => undefined));
        const fit = await nav.evaluate((el) => ({ scroll: el.scrollHeight, client: el.clientHeight }));
        expect(fit.scroll, `sidebar content ${String(fit.scroll)}px > ${String(fit.client)}px`).toBeLessThanOrEqual(
          fit.client,
        );
        await expect(nav.getByTestId("nav-admin")).toBeInViewport();
      });
    }
  }
});

/** Tablet rail: touch users (no hover) can reveal the labels; the choice is remembered. */
test.describe("@responsive tablet rail", () => {
  test.use({ storageState: ADMIN_STATE, viewport: { width: 768, height: 1024 } });

  test("expands to labels and stays expanded after a reload", async ({ page }) => {
    await setPrefs(page, { theme: "light", lang: "ar" });
    await page.goto("/");
    const sidebar = page.locator('[data-slot="app-sidebar"]');
    const toggle = page.getByTestId("rail-toggle");
    await expect(toggle).toBeVisible();
    await expect(sidebar).not.toHaveAttribute("data-labelled", "true");
    await toggle.click();
    await expect(sidebar).toHaveAttribute("data-labelled", "true");
    await expect(sidebar.getByTestId("nav-patients")).toContainText(/\S/);
    await page.reload();
    await expect(page.locator('[data-slot="app-sidebar"]')).toHaveAttribute("data-labelled", "true");
    // Back to the rail for the specs that follow (the choice lives in this browser context only).
    await page.getByTestId("rail-toggle").click();
    await expect(page.locator('[data-slot="app-sidebar"]')).not.toHaveAttribute("data-labelled", "true");
  });
});
