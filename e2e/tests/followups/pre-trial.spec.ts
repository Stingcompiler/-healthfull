/**
 * Pre-trial fixes from the October 2026 inspection (docs/inspection/REPORT-2026-10.md):
 *
 * - F06: the session ends while the doctor's note is half written. The page stays, a sign-in
 *   dialog asks for the password, and the same doctor saves the note afterwards; another user
 *   signing in at that dialog never sees the draft.
 * - F12: the waiting-room kiosk can be signed out (with a confirmation); the design guide is in
 *   the user menu of system administrators only.
 *
 * Filter with `make e2e E2E_GREP=@pretrial`.
 */
import { expect, test, type Page } from "@playwright/test";

import { ANONYMOUS_STATE } from "../../fixtures/state";
import { E2E_PASSWORD } from "../../fixtures/users";
import {
  disposeApiClients,
  expectNoHorizontalScroll,
  login,
  paidVisit,
  setPrefs,
  submitLogin,
  loginForm,
  tr,
} from "../../helpers";

test.describe.configure({ timeout: 150_000 });
test.use({ storageState: ANONYMOUS_STATE });
test.afterAll(disposeApiClients);

const DRAFT = "Fever for two days, written before the session ended";

/** The doctor's workspace for a fresh paid visit, the complaint typed but not saved. */
async function dirtyNote(page: Page): Promise<void> {
  const ready = await paidVisit({ doctor: "pediatrician" });
  await login(page, "pediatrician");
  await setPrefs(page, { theme: "light", lang: "en" });
  await page.goto(`/clinic/visits/${String(ready.visit.id)}`);
  const complaint = page.getByTestId("note-form").getByLabel(tr("en", "clinic:note.complaint"));
  await complaint.fill(DRAFT);
}

/** The server forgets the session (expiry, or a sign-out in another tab). */
async function endSession(page: Page): Promise<void> {
  await page.context().clearCookies({ name: "sessionid" });
}

async function reauth(page: Page, username: string): Promise<void> {
  const dialog = page.getByTestId("reauth-dialog");
  await dialog.getByLabel(tr("en", "auth:login.username")).fill(username);
  await dialog.getByLabel(tr("en", "auth:login.password"), { exact: true }).fill(E2E_PASSWORD);
  await dialog.getByTestId("reauth-submit").click();
}

test.describe("@followups @pretrial session expiry keeps the draft", () => {
  test("the same doctor signs in again and saves the note written before", async ({ page }) => {
    await dirtyNote(page);
    const url = page.url();
    await endSession(page);
    await page.getByTestId("note-save").click();

    const dialog = page.getByTestId("reauth-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText(tr("en", "auth:reauth.title"));
    // Nothing of the page shows behind the dialog, and the page did not move.
    await expect(page.getByTestId("note-form")).toBeHidden();
    expect(page.url()).toBe(url);
    await expectNoHorizontalScroll(page);

    await reauth(page, "pediatrician");
    await expect(dialog).toBeHidden();
    const complaint = page.getByTestId("note-form").getByLabel(tr("en", "clinic:note.complaint"));
    await expect(complaint).toHaveValue(DRAFT);
    await page.getByTestId("note-save").click();
    await expect(page.getByText(tr("en", "clinic:note.savedToast"))).toBeVisible();
    // Saved on the server: a fresh load shows it.
    await page.reload();
    await expect(page.getByTestId("note-form").getByLabel(tr("en", "clinic:note.complaint"))).toHaveValue(DRAFT);
  });

  test("another user signing in at the dialog never sees the draft", async ({ page }) => {
    await dirtyNote(page);
    await endSession(page);
    await page.getByTestId("note-save").click();
    await expect(page.getByTestId("reauth-dialog")).toBeVisible();

    await reauth(page, "nurse");
    await expect(page).toHaveURL(/\/$|\/nursing|\/queue|\/patients/);
    await expect(page.getByTestId("reauth-dialog")).toBeHidden();
    await expect(page.getByTestId("user-menu")).toBeVisible();
    await expect(page.getByText(DRAFT)).toHaveCount(0);
    await expect(page.locator("textarea")).not.toHaveValue(DRAFT);
  });
});

test.describe("@followups @pretrial kiosk and user menu", () => {
  test("the kiosk admin signs the waiting-room screen out after confirming", async ({ page }) => {
    await page.goto("/login");
    await expect(loginForm(page).submit).toBeVisible();
    await submitLogin(page, "display", E2E_PASSWORD);
    await expect(page).toHaveURL(/\/display\/queue/);
    const signOut = page.getByTestId("display-sign-out");
    await expect(signOut).toBeVisible();
    // A tap by chance changes nothing: the screen asks first.
    await signOut.click();
    await page.getByRole("button", { name: tr("en", "common:actions.cancel") }).click();
    await expect(page).toHaveURL(/\/display\/queue/);
    await signOut.click();
    await page
      .getByRole("alertdialog")
      .or(page.getByRole("dialog"))
      .getByRole("button", { name: tr("en", "visits:display.signOut") })
      .click();
    await expect(page).toHaveURL(/\/login/);
    await page.goto("/display/queue");
    await expect(page).toHaveURL(/\/login/);
  });

  for (const [who, sees] of [
    ["admin", true],
    ["doctor", false],
    ["cashier", false],
  ] as const) {
    test(`the design guide is in the user menu of ${who}: ${String(sees)}`, async ({ page }) => {
      await login(page, who);
      await setPrefs(page, { theme: "light", lang: "en" });
      await page.getByTestId("user-menu").click();
      const item = page.getByRole("menuitem", { name: tr("en", "common:user.designSystem") });
      await expect(page.getByTestId("logout")).toBeVisible();
      await expect(item).toHaveCount(sees ? 1 : 0);
    });
  }
});
