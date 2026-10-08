/**
 * Administration: users (FEATURES 0.1, 13.3). The admin creates an account with a role in the
 * UI; that user signs in with the temporary password, must change it, and lands in the app with
 * exactly that role. Then the admin unlocks a locked account with a reason.
 *
 * Passwords here are TEST VALUES created for this throwaway e2e database only.
 */
import { expect, test } from "@playwright/test";

import { ADMIN_STATE, ANONYMOUS_STATE } from "../../fixtures/state";
import { apiAs, csrfHeaders, disposeApiClients, reseed, setPrefs, submitLogin, tr } from "../../helpers";

const TEMP_PASSWORD = "Temp-Pass-2026-e2e";
const NEW_PASSWORD = "Fresh-Pass-2026-e2e";

test.describe("@admin users", () => {
  test.use({ storageState: ADMIN_STATE });
  test.afterAll(async () => {
    await disposeApiClients();
    // The lockout test counts failed logins from this address; the seed clears the counters.
    reseed();
  });

  test("create a user with a role, then sign in as that user", async ({ page, browser }) => {
    const username = `e2e_desk_${String(Date.now())}`;
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/administration/users");
    await expect(page.locator("#main h1")).toHaveText(tr("en", "admin:sections.users.title"));

    await page.getByRole("button", { name: tr("en", "admin:users.create") }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel(tr("en", "admin:users.username")).fill(username);
    await dialog.getByLabel(tr("en", "admin:users.fullNameEn")).fill("Amna Desk");
    await dialog.getByLabel(tr("en", "admin:users.fullNameAr")).fill("آمنة الاستقبال");
    await dialog.getByRole("checkbox", { name: tr("en", "common:roles.receptionist") }).check();
    await dialog.getByLabel(tr("en", "admin:users.tempPassword")).fill(TEMP_PASSWORD);
    await dialog.getByRole("button", { name: tr("en", "actions.save") }).click();
    await expect(page.getByText(tr("en", "admin:users.created", { username }))).toBeVisible();
    await expect(dialog).toBeHidden();

    // The new account is listed with its role and the pending password change.
    await page.getByRole("searchbox").fill(username);
    const row = page.locator("main").getByText("Amna Desk").first();
    await expect(row).toBeVisible();
    await expect(page.locator("main").getByText(tr("en", "admin:users.mustChange")).first()).toBeVisible();

    // Sign in as the new user in a fresh browser: forced password change, then the app.
    const context = await browser.newContext({ storageState: ANONYMOUS_STATE });
    const userPage = await context.newPage();
    await setPrefs(userPage, { theme: "light", lang: "en" });
    await userPage.goto("/login");
    await submitLogin(userPage, username, TEMP_PASSWORD);
    await expect(userPage).toHaveURL(/\/change-password$/);
    await userPage.locator('input[autocomplete="current-password"]').fill(TEMP_PASSWORD);
    await userPage.locator('input[autocomplete="new-password"]').nth(0).fill(NEW_PASSWORD);
    await userPage.locator('input[autocomplete="new-password"]').nth(1).fill(NEW_PASSWORD);
    await userPage.locator('main form button[type="submit"]').click();
    await expect(userPage.getByTestId("user-menu")).toBeVisible();
    await expect(userPage).not.toHaveURL(/change-password/);

    const me = (await (await userPage.context().request.get("/api/auth/me")).json()) as {
      roles: string[];
      must_change_password: boolean;
    };
    expect(me.roles).toEqual(["receptionist"]);
    expect(me.must_change_password).toBe(false);
    // A receptionist has no administration section.
    await expect(userPage.locator("aside").getByTestId("nav-admin")).toHaveCount(0);
    await context.close();
  });

  test("unlock a locked account with a reason", async ({ page }) => {
    const admin = await apiAs("admin");
    const username = `e2e_lock_${String(Date.now())}`;
    await admin.post("/api/core/users", { username, roles: ["nurse"], password: TEMP_PASSWORD });
    // Five wrong passwords lock the account (ADR 0004).
    const headers = await csrfHeaders(page.context());
    for (let i = 0; i < 5; i += 1) {
      const response = await page.context().request.post("/api/auth/login", {
        data: { username, password: "wrong-password" },
        headers,
        failOnStatusCode: false,
      });
      expect([401, 423]).toContain(response.status());
    }

    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/administration/users");
    await page.getByRole("searchbox").fill(username);
    await expect(page.locator("main").getByText(tr("en", "admin:users.locked")).first()).toBeVisible();
    await page.getByRole("button", { name: tr("en", "table.rowActions") }).first().click();
    await page.getByRole("menuitem", { name: tr("en", "admin:users.unlock") }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel(tr("en", "admin:common.reason")).fill("Verified by phone");
    await dialog.getByRole("button", { name: tr("en", "admin:users.unlock") }).click();
    await expect(page.getByText(tr("en", "admin:users.unlocked"))).toBeVisible();
    await expect(page.locator("main").getByText(tr("en", "admin:users.locked"))).toHaveCount(0);
  });
});
