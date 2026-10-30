/**
 * The reception inbox of online bookings (`/visits/online-bookings`, ADR 0029 D, F, G; plan
 * Phase 4, screen of Phase 4b). With approval on, guest requests (booked through the public API
 * as the website does) wait here: reception approves, declines with a reason, issues a new PIN
 * (shown once; the old one stops working), links a booking to a patient file, and declines every
 * open request of one phone. Each row answers on WhatsApp through a plain wa.me link.
 *
 * Approval is switched on for this file and back off afterwards (the seed's state).
 */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import {
  apiAs,
  expectNoHorizontalScroll,
  login,
  setPrefs,
  snap,
  tr,
  trackConsoleErrors,
} from "../../helpers";
import { bookAsGuest, portalPatient, uniquePhone } from "../portal/kit";

async function setApproval(on: boolean): Promise<void> {
  const admin = await apiAs("admin");
  await admin.put("/api/core/public-site", { reason: "e2e: online inbox", require_approval: on });
}

async function openInbox(page: Page, width = 1280): Promise<void> {
  await page.setViewportSize({ width, height: width < 768 ? 812 : 900 });
  await login(page, "reception");
  await setPrefs(page, { theme: "light", lang: "en" });
  await page.goto("/visits/online-bookings");
  await expect(page.getByRole("heading", { name: tr("en", "visits:inbox.title") })).toBeVisible();
}

function row(page: Page, reference: string) {
  return page.getByTestId("inbox-row").filter({ hasText: reference });
}

async function guestSignIn(request: APIRequestContext, reference: string, pin: string): Promise<number> {
  let token = (await request.storageState()).cookies.find((c) => c.name === "csrftoken")?.value;
  if (!token) {
    await request.get("/api/auth/csrf");
    token = (await request.storageState()).cookies.find((c) => c.name === "csrftoken")?.value;
  }
  const response = await request.post("/api/portal/guest-bookings/sign-in", {
    headers: { "X-CSRFToken": token ?? "" },
    data: { reference, pin },
  });
  return response.status();
}

test.describe("@online-inbox reception inbox", () => {
  test.describe.configure({ mode: "serial", timeout: 180_000 });
  test.beforeAll(async () => {
    await setApproval(true);
  });
  test.afterAll(async () => {
    await setApproval(false);
  });

  test("approve and decline requests", async ({ page }) => {
    const a = await bookAsGuest(page.context().request, { name: "Inbox Approve" });
    const b = await bookAsGuest(page.context().request, { name: "Inbox Decline", slot: "last" });
    expect(a.created.status).toBe("requested");

    const logged = trackConsoleErrors(page, { allowAnonymousMe: true });
    await openInbox(page);
    const first = row(page, a.created.reference);
    await expect(first).toBeVisible();
    await expect(first.getByTestId("inbox-status-badge")).toHaveText(tr("en", "visits:appointmentStatus.requested"));
    await expect(first).toContainText(tr("en", "portal:appointments.display.awaiting_approval"));
    const wa = (await first.getByTestId("inbox-whatsapp").getAttribute("href")) ?? "";
    expect(wa).toMatch(/^https:\/\/wa\.me\/249\d+\?text=/);
    expect(decodeURIComponent(wa)).toContain(a.created.reference);
    await expectNoHorizontalScroll(page);

    await first.getByTestId("inbox-approve").click();
    await expect(page.getByText(tr("en", "visits:appointments.approved"))).toBeVisible();
    await expect(first).toHaveCount(0); // the default filter shows requests only

    const second = row(page, b.created.reference);
    await second.getByTestId("inbox-decline").click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("combobox").click();
    await page.getByRole("option", { name: "Declined by reception" }).click();
    await dialog.getByRole("textbox").fill("The doctor is away");
    await dialog.getByRole("button", { name: tr("en", "visits:appointments.decline") }).click();
    await expect(page.getByText(tr("en", "visits:appointments.declined"))).toBeVisible();

    // Every status: the approved one is booked, the declined one cancelled.
    await page.getByTestId("inbox-status").click();
    await page.getByRole("option", { name: tr("en", "visits:inbox.allStatuses"), exact: true }).click();
    await expect(row(page, a.created.reference).getByTestId("inbox-status-badge")).toHaveText(
      tr("en", "visits:appointmentStatus.booked"),
    );
    await expect(row(page, b.created.reference).getByTestId("inbox-status-badge")).toHaveText(
      tr("en", "visits:appointmentStatus.cancelled"),
    );
    expect(logged.errors(), "console errors / page errors").toEqual([]);
  });

  test("issue a new PIN: shown once, the old PIN stops working", async ({ page }) => {
    const { created } = await bookAsGuest(page.context().request, { name: "Inbox Pin" });
    await openInbox(page);
    const target = row(page, created.reference);
    await target.getByTestId("inbox-more").click();
    await page.getByTestId("inbox-pin").click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("textbox").fill("Identity checked on the phone");
    await dialog.getByRole("button", { name: tr("en", "visits:inbox.pinConfirm") }).click();
    const pin = page.getByTestId("inbox-new-pin");
    await expect(pin).toHaveText(/^\d{6}$/);
    const newPin = (await pin.innerText()).trim();
    await page.getByRole("button", { name: tr("en", "visits:inbox.newPinDone") }).click();
    await expect(pin).toHaveCount(0);

    const outside = page.context().request;
    expect(await guestSignIn(outside, created.reference, created.pin ?? "")).toBe(401);
    expect(await guestSignIn(outside, created.reference, newPin)).toBe(200);
  });

  test("link a guest booking to a patient file after checking who came", async ({ page }) => {
    const patient = await portalPatient({});
    const { created } = await bookAsGuest(page.context().request, { name: "Inbox Link" });
    await openInbox(page);
    const target = row(page, created.reference);
    await target.getByTestId("inbox-more").click();
    await page.getByTestId("inbox-link").click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("searchbox").fill(patient.patient.file_no);
    await dialog.getByRole("button").filter({ hasText: patient.patient.file_no }).first().click();
    await dialog.getByTestId("inbox-link-confirm").click();
    await expect(page.getByText(tr("en", "visits:inbox.linked"))).toBeVisible();
    await expect(row(page, created.reference)).toContainText(patient.patient.file_no);
  });

  test("decline every request from one phone, in one confirmed step", async ({ page }) => {
    const phone = uniquePhone();
    const one = await bookAsGuest(page.context().request, { name: "Same Phone", phone });
    // One booking per phone per doctor per day: the second is on the day before.
    const two = await bookAsGuest(page.context().request, { name: "Same Phone", phone, dayFromEnd: 2 });
    await openInbox(page);
    const target = row(page, one.created.reference);
    await expect(target.getByTestId("inbox-phone-requests")).toBeVisible();
    await target.getByTestId("inbox-more").click();
    await page.getByTestId("inbox-decline-phone").click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: tr("en", "visits:inbox.declinePhoneTitle") })).toBeVisible();
    await dialog.getByRole("combobox").click();
    await page.getByRole("option", { name: "Declined by reception" }).click();
    await dialog.getByRole("button", { name: tr("en", "visits:inbox.declinePhoneConfirm") }).click();
    await expect(page.getByText(tr("en", "visits:inbox.declinedPhone_other", { count: "2" }))).toBeVisible();
    await expect(row(page, one.created.reference)).toHaveCount(0);
    await expect(row(page, two.created.reference)).toHaveCount(0);
  });

  test("the inbox in Arabic at 1280 and on a phone", async ({ page }) => {
    await bookAsGuest(page.context().request, { name: "Screens Guest" });
    for (const width of [1280, 768, 375]) {
      await page.setViewportSize({ width, height: width < 768 ? 812 : 900 });
      if (width === 1280) await login(page, "reception");
      await setPrefs(page, { theme: "light", lang: "ar" });
      await page.goto("/visits/online-bookings");
      await expect(page.getByTestId("inbox-row").first()).toBeVisible();
      await expectNoHorizontalScroll(page);
      if (width === 1280) await snap(page, "online-inbox");
    }
  });
});
