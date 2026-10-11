/**
 * Phase 8 follow-up (FEATURES 15.2, ADR 0016): reception issues a portal access code from the
 * patient's file and prints the slip; the new code signs in, the receipt's older code does not;
 * revoking the code ends it. A role without the codes gets 403.
 * Filter with `make e2e E2E_GREP=@followups`.
 */
import { expect, test } from "@playwright/test";

import { ANONYMOUS_STATE } from "../../fixtures/state";
import {
  apiAs,
  csrfHeaders,
  disposeApiClients,
  expectNoHorizontalScroll,
  login,
  setPrefs,
  snap,
  tr,
  trackConsoleErrors,
} from "../../helpers";
import { portalPatient, signInPortal } from "../portal/kit";

test.describe.configure({ timeout: 180_000 });
test.use({ storageState: ANONYMOUS_STATE });
test.afterAll(disposeApiClients);

interface CodesOut {
  codes: { id: number; state: string; revoke_note: string }[];
}

test.describe("@followups @portal reception portal codes", () => {
  test("reception prints a slip; the new code signs in and can be revoked", async ({ page, browser }) => {
    const logged = trackConsoleErrors(page, { allowAnonymousMe: true });
    const who = await portalPatient();

    await page.setViewportSize({ width: 375, height: 812 });
    await page.addInitScript(() => {
      window.print = () => undefined;
    });
    await login(page, "reception");
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto(`/patients/${String(who.patient.id)}`);
    const card = page.getByTestId("portal-access-card");
    await expect(card.getByTestId("portal-access-active")).toBeVisible();
    await card.getByTestId("portal-access-print").click();
    await expect(page).toHaveURL(new RegExp(`/patients/${String(who.patient.id)}/portal-code`));
    await page.getByTestId("portal-code-issue").click();
    // An active code exists: reception confirms that it stops working.
    await page
      .getByRole("button", { name: tr("en", "portal:staff.issueNow") })
      .last()
      .click();
    const code = (await page.getByTestId("portal-slip-code").innerText()).trim();
    expect(code).toMatch(/^\d{4} \d{4}$/);
    await expect(page.getByTestId("portal-slip")).toContainText(who.patient.file_no);
    await expectNoHorizontalScroll(page);
    await snap(page, "followups-portal-slip");

    // The slip's code signs in; the receipt's older code no longer does.
    const portal = await browser.newPage();
    await signInPortal(portal, who, code);
    expect((await portal.context().request.get("/api/portal/me")).status()).toBe(200);
    const other = await browser.newPage();
    const old = await other.context().request.post("/api/portal/session", {
      headers: await csrfHeaders(other.context()),
      data: { file_no: who.patient.file_no, phone: who.patient.phone, code: who.code },
      failOnStatusCode: false,
    });
    expect(old.status()).toBe(401);
    await other.close();

    // Revoke it from the file: the code's session ends.
    await page.goto(`/patients/${String(who.patient.id)}`);
    await card.getByTestId("portal-access-revoke").click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel(tr("en", "reason.code")).fill("Slip lost at the pharmacy");
    await dialog.getByRole("button", { name: tr("en", "portal:staff.revoke") }).click();
    await expect(card.getByTestId("portal-access-none")).toBeVisible();
    const me = await portal.context().request.get("/api/portal/me", { failOnStatusCode: false });
    expect(me.status()).toBe(401);
    await portal.close();

    const reception = await apiAs("reception");
    const codes = await reception.get<CodesOut>(`/api/portal/patients/${String(who.patient.id)}/access-codes`);
    expect(codes.codes[0]?.state).toBe("revoked");
    expect(codes.codes[0]?.revoke_note).toBe("Slip lost at the pharmacy");
    expect(logged.errors()).toEqual([]);
  });

  test("a role without the codes is refused", async () => {
    const who = await portalPatient({ code: false });
    const nurse = await apiAs("nurse");
    const refused = await nurse.post<{ code: string }>(
      `/api/portal/patients/${String(who.patient.id)}/access-codes`,
      {},
      { expect: 403 },
    );
    expect(refused.code).toBe("PERMISSION_DENIED");
  });
});
