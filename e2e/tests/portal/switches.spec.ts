/**
 * The public site switches (ADR 0028, 0029; plan Phase 1). The administrator turns the center
 * website, online booking and patient sign-in on or off at /administration/public-site, with a
 * reason; the server enforces each switch (pytest: apps/portal/tests/test_switches.py) and the
 * SPA follows: the root `/` shows the center website ahead of the sign-in, `/portal` falls back
 * to the patient sign-in or a one-line "not available" page, booking and sign-in actions go.
 *
 * Every test restores the seed's state (all three on) in `finally`, so the rest of the shard
 * sees the portal as before. The screen is in the responsive matrix (e2e/module-routes/admin.ts).
 */
import { expect, test, type Browser, type Page } from "@playwright/test";

import { ADMIN_STATE, ANONYMOUS_STATE } from "../../fixtures/state";
import { apiAs, expectNoHorizontalScroll, setPrefs, tr, trackConsoleErrors } from "../../helpers";
import { LANG, phonePage, portalPatient, signInPortal, t } from "./kit";

interface Switches {
  site_enabled: boolean;
  online_booking_enabled: boolean;
  patient_tracking_enabled: boolean;
}

const ALL_ON: Switches = { site_enabled: true, online_booking_enabled: true, patient_tracking_enabled: true };

async function setSwitches(changes: Partial<Switches>): Promise<void> {
  const admin = await apiAs("admin");
  await admin.put("/api/core/public-site", { reason: "e2e", ...changes });
}

/** A signed-out visitor's page, after the switches changed (the SPA reads them at start). */
async function visitor(browser: Browser, width = 375): Promise<Page> {
  return phonePage(browser, width);
}

test.describe("@public-site switches", () => {
  test.describe.configure({ timeout: 120_000 });
  test.afterEach(async () => {
    await setSwitches(ALL_ON);
  });

  test.describe("signed out", () => {
    test.use({ storageState: ANONYMOUS_STATE });

    test("with the website on, the root and /portal show the center page; staff sign-in stays reachable", async ({
      browser,
    }) => {
      const page = await visitor(browser, 1280);
      const logged = trackConsoleErrors(page, { allowAnonymousMe: true });
      await page.goto("/");
      await expect(page.getByTestId("center-page")).toBeVisible();
      expect(new URL(page.url()).pathname).toBe("/");
      await page.goto("/portal");
      await expect(page.getByTestId("center-page")).toBeVisible();
      await page.goto("/login");
      await expect(page.getByRole("form", { name: t("auth:login.title") })).toBeVisible();
      expect(logged.errors(), "console errors / page errors").toEqual([]);
      await page.context().close();
    });

    test("website off: the root is the staff sign-in, /portal opens the patient sign-in, the page API says SITE_DISABLED", async ({
      browser,
    }) => {
      await setSwitches({ site_enabled: false });
      const page = await visitor(browser);
      await page.goto("/");
      await expect(page).toHaveURL(/\/login(\?|$)/);
      await page.goto("/portal");
      await expect(page).toHaveURL(/\/portal\/sign-in$/);
      const api = await page.context().request.get("/api/portal/center-page");
      expect(api.status()).toBe(404);
      expect(((await api.json()) as { code: string }).code).toBe("SITE_DISABLED");
      // The staff sign-in still shows the center's name and logo (center-identity).
      const identity = await page.context().request.get("/api/portal/center-identity");
      expect(identity.status()).toBe(200);
      await page.context().close();
    });

    test("website and patient sign-in off: /portal is one line, sign-in pages send back to it", async ({
      browser,
    }) => {
      await setSwitches({ site_enabled: false, patient_tracking_enabled: false });
      const page = await visitor(browser);
      await page.goto("/portal");
      await expect(page.getByTestId("portal-services-off")).toBeVisible();
      await expect(page.getByRole("heading", { name: t("portal:off.title") })).toBeVisible();
      await page.goto("/portal/sign-in");
      await expect(page).toHaveURL(/\/portal$/);
      await page.goto("/portal/home");
      await expect(page).toHaveURL(/\/portal$/);
      await expectNoHorizontalScroll(page);
      await page.context().close();
    });

    test("patient sign-in off: the center page keeps its facts and drops every sign-in action", async ({
      browser,
    }) => {
      await setSwitches({ patient_tracking_enabled: false });
      const page = await visitor(browser);
      await page.goto("/portal");
      await expect(page.getByTestId("center-page")).toBeVisible();
      await expect(page.getByTestId("center-sign-in")).toHaveCount(0);
      await expect(page.getByTestId("center-sticky-bar")).toHaveCount(0);
      await expect(page.getByTestId("portal-header-sign-in")).toHaveCount(0);
      await expect(page.getByTestId("quick-book")).toHaveCount(0);
      await page.context().close();
    });
  });

  test("online booking off: a signed-in patient keeps the list and loses booking", async ({ browser }) => {
    const patient = await portalPatient({ appointment: true });
    await setSwitches({ online_booking_enabled: false });
    const page = await phonePage(browser);
    await signInPortal(page, patient);
    await page.goto("/portal/appointments");
    await expect(page.getByTestId("appointments-upcoming")).toBeVisible();
    await expect(page.getByTestId("appointments-book")).toHaveCount(0);
    await page.goto("/portal/appointments/new");
    await expect(page).toHaveURL(/\/portal\/appointments$/);
    const doctors = await page.context().request.get("/api/portal/doctors");
    expect(((await doctors.json()) as { code: string }).code).toBe("ONLINE_BOOKING_DISABLED");
    await page.context().close();
  });

  test("turning patient sign-in off signs a patient out", async ({ browser }) => {
    const patient = await portalPatient({});
    const page = await phonePage(browser);
    await signInPortal(page, patient);
    await page.goto("/portal/home");
    await expect(page).toHaveURL(/\/portal\/home$/);
    await setSwitches({ patient_tracking_enabled: false });
    const me = await page.context().request.get("/api/portal/me");
    expect(me.status()).toBe(409);
    expect(((await me.json()) as { code: string }).code).toBe("PORTAL_DISABLED");
    await page.context().close();
  });

  test.describe("administration", () => {
    test.use({ storageState: ADMIN_STATE });

    test("the administrator switches the website off with a reason, and the root follows", async ({
      page,
      browser,
    }) => {
      await page.setViewportSize({ width: 1280, height: 800 });
      const logged = trackConsoleErrors(page);
      await setPrefs(page, { theme: "light", lang: LANG });
      await page.goto("/administration/public-site");
      const form = page.getByTestId("public-site-form");
      await expect(form).toBeVisible();
      await expect(page.getByTestId("public-site-live")).toContainText(t("admin:publicSite.liveSite"));
      await page.getByRole("switch", { name: t("admin:publicSite.site") }).click();
      await page.getByTestId("public-site-save").click();
      // The reason is required before anything is sent.
      await expect(page.getByLabel(t("admin:publicSite.reason"))).toHaveAttribute("aria-invalid", "true");
      await page.getByLabel(t("admin:publicSite.reason")).fill("Website under review");
      await page.getByTestId("public-site-save").click();
      await expect(page.getByText(t("admin:publicSite.saved"))).toBeVisible();
      await expect(page.getByTestId("public-site-live")).not.toContainText(t("admin:publicSite.liveSite"));

      // A visitor without the admin's session (the test's storage state would carry it).
      const anonymous = await browser.newContext({ storageState: ANONYMOUS_STATE });
      const outside = await anonymous.newPage();
      await outside.goto("/");
      await expect(outside).toHaveURL(/\/login(\?|$)/);
      await outside.context().close();
      expect(logged.errors(), "console errors / page errors").toEqual([]);
    });

    test("a rule out of range is refused on the form", async ({ page }) => {
      await setPrefs(page, { theme: "light", lang: LANG });
      await page.goto("/administration/public-site");
      const horizon = page.getByLabel(t("admin:publicSite.horizon"));
      await horizon.fill("0");
      await page.getByLabel(t("admin:publicSite.reason")).fill("try");
      await page.getByTestId("public-site-save").click();
      await expect(page.getByText(tr(LANG, "admin:publicSite.range", { min: "1", max: "365" }))).toBeVisible();
    });
  });
});
