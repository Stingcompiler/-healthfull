import { expect, type APIRequestContext, type BrowserContext, type Page } from "@playwright/test";

import { BASE_URL } from "../env";
import { E2E_PASSWORD, resolveUser, type RoleCode, type UserKey } from "../fixtures/users";

/** Headers for an unsafe API call made outside the SPA (Django CSRF). */
export async function csrfHeaders(context: BrowserContext): Promise<Record<string, string>> {
  let token = (await context.cookies(BASE_URL)).find((c) => c.name === "csrftoken")?.value;
  if (!token) {
    const response = await context.request.get("/api/auth/csrf");
    expect(response.status(), "GET /api/auth/csrf").toBe(204);
    token = (await context.cookies(BASE_URL)).find((c) => c.name === "csrftoken")?.value;
  }
  if (!token) throw new Error("csrftoken cookie was not set by /api/auth/csrf");
  return { "X-CSRFToken": token };
}

/** True when the page's browser context holds a live session. */
export async function isLoggedIn(page: Page): Promise<boolean> {
  const response = await page.context().request.get("/api/auth/me");
  return response.status() === 200;
}

/** The fields of the login form, by stable attributes (labels are translated). */
export function loginForm(page: Page) {
  return {
    username: page.locator('input[autocomplete="username"]'),
    password: page.locator('input[autocomplete="current-password"]'),
    submit: page.locator('main form button[type="submit"]'),
    alert: page.locator("main form").getByRole("alert"),
  };
}

/** Fills and submits the login form on the current page (already at /login). */
export async function submitLogin(page: Page, username: string, password: string): Promise<void> {
  const form = loginForm(page);
  await form.username.fill(username);
  await form.password.fill(password);
  await form.submit.click();
}

/**
 * Logs in through the real login screen and waits for the app shell.
 * `login(page, "cashier")` or by role code `login(page, "lab_supervisor")`.
 * Leaves the page on the post-login route.
 */
export async function login(
  page: Page,
  who: UserKey | RoleCode,
  options: { redirect?: string } = {},
): Promise<void> {
  const target = options.redirect ? `/login?redirect=${encodeURIComponent(options.redirect)}` : "/login";
  await page.goto(target);
  await expect(loginForm(page).submit).toBeVisible();
  await submitLogin(page, resolveUser(who).username, E2E_PASSWORD);
  await expect(page).not.toHaveURL(/\/login(\?|$)/);
  await expect(page.getByTestId("user-menu")).toBeVisible();
}

/** Logs in with the API only (no UI), e.g. to build a storage state. */
export async function apiLogin(request: APIRequestContext, who: UserKey | RoleCode): Promise<void> {
  const csrf = await request.get("/api/auth/csrf");
  expect(csrf.status(), "GET /api/auth/csrf").toBe(204);
  const state = await request.storageState();
  const token = state.cookies.find((c) => c.name === "csrftoken")?.value;
  if (!token) throw new Error("csrftoken cookie was not set by /api/auth/csrf");
  const response = await request.post("/api/auth/login", {
    headers: { "X-CSRFToken": token },
    data: { username: resolveUser(who).username, password: E2E_PASSWORD },
  });
  expect(response.status(), `login as ${who}: ${await response.text()}`).toBe(200);
}

/** Logs out through the user menu and waits for the login screen. */
export async function logout(page: Page): Promise<void> {
  await page.getByTestId("user-menu").click();
  await page.getByTestId("logout").click();
  await expect(page).toHaveURL(/\/login(\?|$)/);
  await expect(loginForm(page).submit).toBeVisible();
}
