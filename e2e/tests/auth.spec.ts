/**
 * Sign-in, failure messages, lockout and sign-out against the real backend
 * (auth API contract in ARCHITECTURE 4.11 / backend apps/core/api.py).
 *
 * Each test uses its own seed user so the failure counters never interact:
 *   success: reception, doctor, cashier, pharmacist, manager, admin
 *   wrong password: accountant        lockout: labtech
 *   logout: cashsup                   deep link: nurse
 */
import { expect, test, type Page, type Response } from "@playwright/test";

import { BASE_URL } from "../env";
import { ANONYMOUS_STATE } from "../fixtures/state";
import { E2E_PASSWORD, USERS, type UserKey } from "../fixtures/users";
import {
  expectPrefsApplied,
  isLoggedIn,
  login,
  loginForm,
  logout,
  reseed,
  setPrefs,
  submitLogin,
  tr,
  type Lang,
} from "../helpers";

test.use({ storageState: ANONYMOUS_STATE });

interface MeOut {
  username: string;
  roles: string[];
  permissions: string[];
  language: Lang;
}

async function me(page: Page): Promise<MeOut> {
  const response = await page.context().request.get("/api/auth/me");
  expect(response.status()).toBe(200);
  return (await response.json()) as MeOut;
}

/** Submits the login form and returns the API response it produced. */
async function attempt(page: Page, username: string, password: string): Promise<Response> {
  const responded = page.waitForResponse(
    (r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/auth/login",
  );
  await submitLogin(page, username, password);
  return responded;
}

/** The language switcher's accessible name is written in the current language. */
function switchLanguageButton(page: Page, current: Lang) {
  const target: Lang = current === "ar" ? "en" : "ar";
  const name = tr(current, "language.switchTo", { language: tr(current, `language.${target}`) });
  return page.getByRole("button", { name, exact: true });
}

/**
 * Who sees the Administration entry with the default permission matrix
 * (backend apps/core/permissions.py): the admin role (every permission) and the
 * manager, who holds core.manage_settings and ops.view_status by default.
 */
const SEES_ADMINISTRATION: ReadonlySet<UserKey> = new Set<UserKey>(["admin", "manager"]);

test.describe("@auth sign in", () => {
  const roles: UserKey[] = ["reception", "doctor", "cashier", "pharmacist", "manager", "admin"];
  for (const key of roles) {
    test(`${key} signs in and lands on the dashboard`, async ({ page }) => {
      const user = USERS[key];
      await setPrefs(page, { theme: "light", lang: "en" });
      await login(page, key);
      await expect(page).toHaveURL(`${BASE_URL}/`);

      const profile = await me(page);
      expect(profile.username).toBe(user.username);
      expect(profile.roles).toEqual([user.role]);

      // The dashboard greets the user by name in the profile's language (the server wins over the cache).
      const name = profile.language === "ar" ? user.fullNameAr : user.fullNameEn;
      await expect(page.locator("#main h1")).toContainText(name);
      await expectPrefsApplied(page, { theme: "light", lang: profile.language });

      // Navigation is filtered by the permissions /me returns (UI only; the server enforces).
      const adminNav = page.locator("aside").getByTestId("nav-admin");
      if (SEES_ADMINISTRATION.has(key)) await expect(adminNav).toBeVisible();
      else await expect(adminNav).toHaveCount(0);
      if (key === "manager") {
        expect(profile.permissions).toEqual(expect.arrayContaining(["core.manage_settings", "ops.view_status"]));
        expect(profile.permissions).not.toContain("core.manage_users");
      }
    });
  }

  test("a deep link survives the login detour", async ({ page }) => {
    await page.goto("/reports");
    await expect(page).toHaveURL(/\/login\?redirect=/);
    expect(new URL(page.url()).searchParams.get("redirect")).toBe("/reports");
    await expect(loginForm(page).submit).toBeVisible();
    await submitLogin(page, USERS.nurse.username, E2E_PASSWORD);
    await expect(page).toHaveURL(`${BASE_URL}/reports`);
    await expect(page.locator("#main h1")).toBeVisible();
  });
});

test.describe("@auth failures", () => {
  test("a wrong password shows the translated error in Arabic and English", async ({ page }) => {
    const form = loginForm(page);
    await setPrefs(page, { theme: "light", lang: "ar" });
    await page.goto("/login");
    await expectPrefsApplied(page, { theme: "light", lang: "ar" });

    let response = await attempt(page, USERS.accountant.username, "not-the-password");
    expect(response.status()).toBe(401);
    await expect(form.alert).toContainText(tr("ar", "auth:login.failedTitle"));
    await expect(form.alert).toContainText(tr("ar", "errors:INVALID_CREDENTIALS"));
    await expect(form.password).toHaveValue("");

    // Switch with the real language switcher: direction flips and the shown error re-translates.
    await switchLanguageButton(page, "ar").click();
    await expectPrefsApplied(page, { theme: "light", lang: "en" });
    await expect(form.alert).toContainText(tr("en", "errors:INVALID_CREDENTIALS"));

    response = await attempt(page, USERS.accountant.username, "still-not-the-password");
    expect(response.status()).toBe(401);
    await expect(form.alert).toContainText(tr("en", "auth:login.failedTitle"));
    await expect(form.alert).toContainText(tr("en", "errors:INVALID_CREDENTIALS"));

    // The right password still works (and resets the failure counter).
    response = await attempt(page, USERS.accountant.username, E2E_PASSWORD);
    expect(response.status()).toBe(200);
    await expect(page.getByTestId("user-menu")).toBeVisible();
  });

  test.describe("lockout", () => {
    // labtech ends locked for 15 minutes; put the seed back for later runs on this database.
    test.afterAll(() => {
      reseed();
    });

    test("five failed attempts lock the account, even against the right password", async ({ page }) => {
      const form = loginForm(page);
      await setPrefs(page, { theme: "light", lang: "en" });
      await page.goto("/login");

      // Failures 1-5 are plain credential errors; the 5th one sets the 15-minute lock.
      for (let i = 1; i <= 5; i += 1) {
        const response = await attempt(page, USERS.labtech.username, `wrong-password-${String(i)}`);
        expect(response.status(), `attempt ${String(i)}`).toBe(401);
        await expect(form.alert).toContainText(tr("en", "errors:INVALID_CREDENTIALS"));
      }

      // From then on every attempt is refused as locked, the correct password included.
      const locked = await attempt(page, USERS.labtech.username, E2E_PASSWORD);
      expect(locked.status()).toBe(423);
      const body = (await locked.json()) as { code: string; details: { locked_until?: string } };
      expect(body.code).toBe("ACCOUNT_LOCKED");
      expect(body.details.locked_until).toBeTruthy();

      await expect(form.alert).toContainText(tr("en", "auth:login.lockedTitle"));
      await expect(form.alert).toContainText(tr("en", "errors:ACCOUNT_LOCKED"));
      const untilPrefix = tr("en", "auth:login.lockedUntil").split("{{")[0] ?? "";
      await expect(form.alert).toContainText(untilPrefix.trim());
      await expect(page).toHaveURL(/\/login/);
      expect(await isLoggedIn(page)).toBe(false);

      // The locked message is translated too.
      await switchLanguageButton(page, "en").click();
      await expectPrefsApplied(page, { theme: "light", lang: "ar" });
      await expect(form.alert).toContainText(tr("ar", "auth:login.lockedTitle"));
      await expect(form.alert).toContainText(tr("ar", "errors:ACCOUNT_LOCKED"));
    });
  });
});

test.describe("@auth sign out", () => {
  test("logout ends the session and protected pages send you back to login", async ({ page }) => {
    await login(page, "cashsup");
    expect(await isLoggedIn(page)).toBe(true);

    await logout(page);
    expect(await isLoggedIn(page)).toBe(false);

    await page.goto("/design");
    await expect(page).toHaveURL(/\/login\?redirect=/);
    expect(new URL(page.url()).searchParams.get("redirect")).toBe("/design");
    await expect(loginForm(page).submit).toBeVisible();
  });
});
