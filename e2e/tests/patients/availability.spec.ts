/**
 * Availability hardening (public site Phase 3, ADR 0029 C, E): reception approves or declines
 * an online request on the doctor's day; the administrator plans a doctor's time off from the
 * doctors' schedule list and sets the approval rules on the public site screen. Each screen at
 * phone, tablet and desktop widths without horizontal scroll.
 */
import { expect, test, type Page } from "@playwright/test";

import { ADMIN_STATE } from "../../fixtures/state";
import {
  apiAs,
  disposeApiClients,
  expectNoHorizontalScroll,
  fixture,
  login,
  setPrefs,
  tr,
} from "../../helpers";

test.describe.configure({ timeout: 120_000 });
test.afterAll(disposeApiClients);

const WIDTHS = [
  { width: 375, height: 812 },
  { width: 768, height: 1024 },
  { width: 1280, height: 800 },
] as const;

interface OnlineRequest {
  id: number;
  starts_at: string;
  day: string;
  doctor_id: number;
  doctor_name_en: string;
}

async function openDay(page: Page, request: OnlineRequest): Promise<void> {
  await page.goto("/appointments");
  await page
    .getByRole("combobox", { name: tr("en", "visits:appointments.doctor") })
    .click();
  await page
    .getByRole("option", { name: request.doctor_name_en, exact: true })
    .click();
  await page.locator("#agenda-day").fill(request.day);
}

for (const size of WIDTHS) {
  test(`@availability reception approves and declines online requests (${String(size.width)}px)`, async ({
    page,
  }) => {
    const tag = String(Date.now()).slice(-6);
    const one = await fixture<OnlineRequest>("online_request", {
      doctor: "dentist",
      contact_name: `Online ${tag} A`,
    });
    await fixture<OnlineRequest>("online_request", {
      doctor: "dentist",
      contact_name: `Online ${tag} B`,
    });
    await page.setViewportSize(size);
    await login(page, "reception");
    await setPrefs(page, { theme: "light", lang: "en" });
    await openDay(page, one);

    const first = page
      .getByTestId("appointment")
      .filter({ hasText: `Online ${tag} A` });
    await expect(first).toHaveAttribute("data-status", "requested");
    await expect(first.getByTestId("request-expires")).toBeVisible();
    await expectNoHorizontalScroll(page);
    await first.getByTestId("request-approve").click();
    await expect(
      page.getByText(tr("en", "visits:appointments.approved")),
    ).toBeVisible();
    await expect(first).toHaveAttribute("data-status", "booked");

    const second = page
      .getByTestId("appointment")
      .filter({ hasText: `Online ${tag} B` });
    await second.getByTestId("request-decline").click();
    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByRole("heading", {
        name: tr("en", "visits:appointments.declineTitle"),
      }),
    ).toBeVisible();
    await dialog.getByRole("combobox").click();
    await page.getByRole("option", { name: "Declined by reception" }).click();
    await dialog
      .getByRole("textbox")
      .fill("The doctor is fully booked that day");
    await dialog
      .getByRole("button", { name: tr("en", "visits:appointments.decline") })
      .click();
    await expect(
      page.getByText(tr("en", "visits:appointments.declined")),
    ).toBeVisible();
    await expect(second).toHaveAttribute("data-status", "cancelled");
  });
}

test.describe("@availability administration", () => {
  test.use({ storageState: ADMIN_STATE });

  for (const size of WIDTHS) {
    test(`time off of a doctor (${String(size.width)}px)`, async ({ page }) => {
      await page.setViewportSize(size);
      await setPrefs(page, { theme: "light", lang: "en" });
      await page.goto("/administration/departments");
      await page
        .getByRole("tab", { name: tr("en", "admin:departments.doctorsTab") })
        .click();
      await page
        .locator("#main")
        .getByRole("button", { name: tr("en", "table.rowActions") })
        .first()
        .click();
      await page
        .getByRole("menuitem", { name: tr("en", "admin:timeOff.action") })
        .click();

      const dialog = page.getByRole("dialog");
      await expect(dialog.getByTestId("time-off-list")).toBeVisible();
      const year = new Date().getFullYear() + 1;
      const day = `${String(year)}-0${String((size.width % 9) + 1)}-1${String(size.width % 7)}`;
      await dialog.getByLabel(tr("en", "admin:timeOff.fromDay")).fill(day);
      await dialog.getByLabel(tr("en", "admin:timeOff.toDay")).fill(day);
      await dialog
        .getByLabel(tr("en", "admin:timeOff.reasonEn"))
        .fill("Conference");
      await expectNoHorizontalScroll(page);
      await dialog
        .getByRole("button", { name: tr("en", "admin:timeOff.add") })
        .click();
      await expect(
        page.getByText(tr("en", "admin:timeOff.added")),
      ).toBeVisible();
      const added = dialog
        .getByTestId("time-off-row")
        .filter({ hasText: "Conference" });
      await expect(added.first()).toBeVisible();

      await added.first().getByTestId("time-off-remove").click();
      await page
        .getByRole("alertdialog")
        .getByRole("button", { name: tr("en", "admin:timeOff.remove") })
        .click();
      await expect(
        page.getByText(tr("en", "admin:timeOff.removed")),
      ).toBeVisible();
    });
  }

  test("public site approval and reschedule rules", async ({ page }) => {
    const admin = await apiAs("admin");
    const before = await admin.get<{ require_approval: boolean }>(
      "/api/core/public-site",
    );
    for (const size of WIDTHS) {
      await page.setViewportSize(size);
      await setPrefs(page, { theme: "light", lang: "en" });
      await page.goto("/administration/public-site");
      await expect(page.getByTestId("public-site-form")).toBeVisible();
      await expect(
        page.getByLabel(tr("en", "admin:publicSite.requireApproval")),
      ).toBeVisible();
      await expect(
        page.getByLabel(tr("en", "admin:publicSite.rescheduleCutoff")),
      ).toBeVisible();
      await expectNoHorizontalScroll(page);
    }
    expect(before.require_approval).toBe(false); // the e2e dataset books instantly
  });
});
