/**
 * Phase 8 follow-up (FEATURES 0.2, 2.3, ADR 0019): the waiting-room kiosk signs in with the
 * `display` role, lands on /display/queue, is sent back there from any staff screen, and the
 * server refuses it everything but the queue feed.
 * Filter with `make e2e E2E_GREP=@followups`.
 */
import { expect, test } from "@playwright/test";

import { ANONYMOUS_STATE } from "../../fixtures/state";
import { E2E_PASSWORD } from "../../fixtures/users";
import {
  apiAs,
  disposeApiClients,
  expectNoHorizontalScroll,
  loginForm,
  paidVisit,
  setPrefs,
  snap,
  submitLogin,
  trackConsoleErrors,
} from "../../helpers";

test.describe.configure({ timeout: 120_000 });
test.use({ storageState: ANONYMOUS_STATE });
test.afterAll(disposeApiClients);

test.describe("@followups @patients display role", () => {
  test("the kiosk account sees the waiting room and nothing else", async ({ page }) => {
    const logged = trackConsoleErrors(page, { allowAnonymousMe: true });
    await paidVisit({
      patient_fields: { full_name_en: "Rashid Abdelgadir Mohamed Nour" },
    });

    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/login");
    await expect(loginForm(page).submit).toBeVisible();
    await submitLogin(page, "display", E2E_PASSWORD);
    await expect(page).toHaveURL(/\/display\/queue/);
    await expect(page.getByTestId("queue-display")).toBeVisible();
    await expect(page.getByTestId("user-menu")).toHaveCount(0);
    await setPrefs(page, { theme: "dark", lang: "ar" });
    // The paid token is on the screen, the clinic picker comes from the feed itself.
    await expect(page.locator('[data-testid="queue-display"] #display-now')).toBeVisible();
    await page.getByRole("combobox").first().click();
    await expect(page.getByRole("option").nth(1)).toBeVisible();
    await page.keyboard.press("Escape");
    await expectNoHorizontalScroll(page);
    await snap(page, "followups-display-role");

    // Any staff screen sends the kiosk back to the waiting room.
    for (const path of ["/", "/patients", "/cashier", "/administration"]) {
      await page.goto(path);
      await expect(page).toHaveURL(/\/display\/queue/);
    }
    expect(logged.errors()).toEqual([]);
  });

  test("the server refuses the kiosk every staff read and write", async () => {
    const kiosk = await apiAs("display");
    const me = await kiosk.get<{ roles: string[]; permissions: string[] }>("/api/auth/me");
    expect(me.roles).toEqual(["display"]);
    expect(me.permissions).toEqual(["visits.view_display"]);
    expect((await kiosk.get<{ waiting: unknown[] }>("/api/visits/queue/display")).waiting).toBeDefined();
    for (const path of ["/api/patients", "/api/visits/queue/board", "/api/visits/options", "/api/billing/lookup"]) {
      const refused = await kiosk.get<{ code: string }>(path, { expect: 403 });
      expect(refused.code, path).toBe("PERMISSION_DENIED");
    }
    const refused = await kiosk.post<{ code: string }>("/api/visits/queue/call-next", {}, { expect: 403 });
    expect(refused.code).toBe("PERMISSION_DENIED");
  });
});
