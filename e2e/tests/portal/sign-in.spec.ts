/**
 * Portal sign-in (FEATURES 15.2, ADR 0016): the cashier prints an access code on the receipt
 * and the patient signs in with it on a phone; wrong codes lock the file number out; signing
 * out ends the session.
 */
import { expect, test } from "@playwright/test";

import { login, setPrefs } from "../../helpers";
import { fillSignIn, LANG, phonePage, portalPatient, signInPortal, t } from "./kit";

test.describe("@portal sign-in", () => {
  test.describe.configure({ timeout: 120_000 });

  test("the cashier prints a code on the receipt and the patient signs in with it", async ({ browser }) => {
    const who = await portalPatient({ code: false });

    const cashierContext = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const cashier = await cashierContext.newPage();
    await login(cashier, "cashier");
    await setPrefs(cashier, { theme: "light", lang: LANG });
    await cashier.goto(`/cashier/receipts/${String(who.payment.id)}`);
    await expect(cashier.getByTestId("receipt-qr").first()).toBeVisible();
    await cashier.getByTestId("receipt-portal-issue").first().click();
    const printed = cashier.getByTestId("receipt-portal-code-value").first();
    await expect(printed).toHaveText(/^\d{4} \d{4}$/);
    const code = (await printed.textContent()) ?? "";
    await cashierContext.close();

    const page = await phonePage(browser);
    await page.goto("/portal");
    await fillSignIn(page, who.patient.file_no, who.patient.phone, code);
    await expect(page).toHaveURL(/\/portal\/home$/);
    await expect(page.getByTestId("home-balance")).toBeVisible();
    await expect(page.getByText(who.patient.file_no)).toBeVisible();
    // Only the portal cookie: no staff session came with it.
    const cookies = (await page.context().cookies()).map((c) => c.name);
    expect(cookies).toContain("hospital_portal");
    expect(cookies).not.toContain("sessionid");
    expect((await page.context().request.get("/api/auth/me")).status()).toBe(401);
  });

  test("wrong codes lock the file number out", async ({ browser }) => {
    const who = await portalPatient();
    const page = await phonePage(browser);
    await page.goto("/portal");
    for (let attempt = 1; attempt <= 5; attempt++) {
      await fillSignIn(page, who.patient.file_no, who.patient.phone, "1111 1111");
      await expect(page.getByText(t("errors:PORTAL_INVALID_CREDENTIALS"))).toBeVisible();
    }
    // The sixth attempt is refused even with the right code.
    await fillSignIn(page, who.patient.file_no, who.patient.phone, who.code ?? "");
    await expect(page.getByText(t("errors:PORTAL_LOCKED"))).toBeVisible();
    await expect(page).toHaveURL(/\/portal\/?$/);
  });

  test("signing out ends the session", async ({ browser }) => {
    const who = await portalPatient();
    const page = await phonePage(browser);
    await signInPortal(page, who);
    await page.goto("/portal/home");
    await expect(page.getByTestId("home-balance")).toBeVisible();
    await page.getByTestId("portal-sign-out").click();
    await expect(page.getByText(t("portal:login.signedOut"))).toBeVisible();
    await page.goto("/portal/results");
    await expect(page.getByText(t("portal:login.expired"))).toBeVisible();
    expect((await page.context().request.get("/api/portal/me")).status()).toBe(401);
  });
});
