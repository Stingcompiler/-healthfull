/**
 * Booking on the portal (FEATURES 2.5, 15.2): a free slot of a doctor's schedule, then an
 * online cancellation before the cut-off. Days and times come from the server's schedule, so
 * the spec does not depend on the hour it runs.
 */
import { expect, test } from "@playwright/test";

import { phonePage, portalPatient, signInPortal, t } from "./kit";

test.describe("@portal booking", () => {
  test.describe.configure({ timeout: 120_000 });

  test("books an appointment and cancels it", async ({ browser }) => {
    const who = await portalPatient();
    const page = await phonePage(browser);
    await signInPortal(page, who);

    await page.goto("/portal/appointments");
    await expect(page.getByText(t("portal:appointments.none"))).toBeVisible();
    await page.getByTestId("appointments-book").click();
    await expect(page).toHaveURL(/\/portal\/appointments\/new$/);

    await page.getByTestId("book-doctor").first().click();
    const day = page.getByTestId("book-day").last(); // the furthest day: past any cut-off
    await expect(day).toBeVisible();
    await day.click();
    const slot = page.getByTestId("book-slot").first();
    await expect(slot).toBeVisible();
    await slot.click();
    await expect(page.getByTestId("book-summary")).toContainText(":");
    await page.getByTestId("book-confirm").click();

    await expect(page).toHaveURL(/\/portal\/appointments$/);
    await expect(page.getByText(t("portal:book.booked"))).toBeVisible();
    const row = page.getByTestId("appointment-row");
    await expect(row).toHaveCount(1);
    await expect(row).toContainText(t("portal:appointments.status.booked"));

    await row.getByTestId("appointment-cancel").click();
    await page.getByRole("button", { name: t("portal:appointments.cancelConfirm") }).click();
    await expect(page.getByText(t("portal:appointments.cancelled"))).toBeVisible();
    await expect(page.getByText(t("portal:appointments.none"))).toBeVisible();
  });
});
