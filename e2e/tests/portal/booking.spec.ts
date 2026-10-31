/**
 * Booking on the portal (FEATURES 2.5, 15.2): a free slot of a doctor's schedule, then an
 * online cancellation before the cut-off. Days and times come from the server's schedule, so
 * the spec does not depend on the hour it runs.
 *
 * The signed-in booking and reschedule wear the guest booking's design inside the portal's own
 * header and tab bar (D-0024): a two-step stepper (doctor and time, then review), doctor cards and
 * day and time chips shown as they can be chosen, a glass action bar above the phone tab bar, and
 * from lg a sticky summary beside the step.
 */
import { expect, test, type Page } from "@playwright/test";

import {
  expectNoHorizontalScroll,
  expectStepLabelsApart,
  setPrefs,
  snap,
  tr,
  type Lang,
} from "../../helpers";
import { phonePage, portalPatient, signInPortal, t } from "./kit";

async function chooseSlot(page: Page, which: "first" | "last"): Promise<void> {
  const day = page.getByTestId("book-day").last(); // the furthest day: past any cut-off
  await expect(day).toBeVisible();
  await day.click();
  const slot = page.getByTestId("book-slot")[which]();
  await expect(slot).toBeVisible();
  await slot.click();
}

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

    // Step 1 of 2: the day and the time appear only once they can be chosen.
    const stepper = page.getByTestId("book-step");
    await expect(stepper.locator('[aria-current="step"]')).toContainText(
      t("portal:book.steps.slot"),
    );
    await expect(page.getByTestId("book-day")).toHaveCount(0);
    await expect(page.getByTestId("book-slot")).toHaveCount(0);
    await expect(page.getByTestId("book-next")).toBeDisabled();
    await page.getByTestId("book-doctor").first().click();
    await chooseSlot(page, "first");
    await expect(page.getByTestId("book-summary")).toContainText(":");
    // The phone's action bar floats above the tab bar, never under it.
    const next = await page.getByTestId("book-next").boundingBox();
    const tabs = await page.locator('[data-slot="portal-nav"]').boundingBox();
    expect((next?.y ?? 9999) + (next?.height ?? 0)).toBeLessThanOrEqual(
      tabs?.y ?? 0,
    );
    await expectStepLabelsApart(page, '[data-testid="book-step"]');
    await expectNoHorizontalScroll(page);

    // Step 2 of 2: review, then book.
    await page.getByTestId("book-next").click();
    await expect(stepper.locator('[aria-current="step"]')).toContainText(
      t("portal:book.steps.review"),
    );
    const review = page.getByTestId("book-review-step");
    await expect(review.getByTestId("book-review")).toContainText(":");
    await expect(review.getByTestId("guest-fees")).toContainText(
      t("portal:center.fees.text"),
    );
    await page.getByTestId("book-confirm").click();

    await expect(page).toHaveURL(/\/portal\/appointments$/);
    await expect(page.getByText(t("portal:book.booked"))).toBeVisible();
    const row = page.getByTestId("appointment-row");
    await expect(row).toHaveCount(1);
    await expect(row).toContainText(t("portal:appointments.display.confirmed"));

    // Move it to another free time (ADR 0029 A7): the old booking shows as moved.
    await row.getByTestId("appointment-reschedule").click();
    await expect(page).toHaveURL(/\/portal\/appointments\/\d+\/reschedule$/);
    await expect(page.getByTestId("book-doctor").first()).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await expect(page.getByTestId("book-summary")).toContainText(
      t("portal:book.currentAppointment"),
    );
    await chooseSlot(page, "last");
    await page.getByTestId("book-next").click();
    await expect(page.getByTestId("book-review")).toContainText(
      t("portal:book.currentAppointment"),
    );
    await page.getByTestId("book-confirm").click();
    await expect(page).toHaveURL(/\/portal\/appointments$/);
    await expect(page.getByText(t("portal:book.moved"))).toBeVisible();
    await expect(
      page.getByTestId("appointments-upcoming").getByTestId("appointment-row"),
    ).toHaveCount(1);
    await expect(
      page.getByText(t("portal:appointments.display.moved"), { exact: true }),
    ).toBeVisible();

    await page
      .getByTestId("appointments-upcoming")
      .getByTestId("appointment-cancel")
      .click();
    await page
      .getByRole("button", { name: t("portal:appointments.cancelConfirm") })
      .click();
    await expect(
      page.getByText(t("portal:appointments.cancelled")),
    ).toBeVisible();
    await expect(page.getByText(t("portal:appointments.none"))).toBeVisible();
  });

  test("the booking screen in the guest booking's design at 375, 768 and 1280 (ar), in the portal's own shell", async ({
    browser,
  }) => {
    const lang: Lang = "ar";
    const who = await portalPatient();
    for (const size of [
      { width: 375, height: 812 },
      { width: 768, height: 1024 },
      { width: 1280, height: 800 },
    ]) {
      const page = await phonePage(browser, size.width);
      await page.setViewportSize(size);
      await setPrefs(page, { theme: "light", lang });
      await signInPortal(page, who);
      await page.goto("/portal/appointments/new");
      await expect(page.getByTestId("book-doctor").first()).toBeVisible();
      // The signed-in shell: the portal tabs, not the website's footer.
      await expect(page.locator('[data-slot="portal-nav"]')).toBeVisible();
      await expect(page.getByTestId("center-footer")).toHaveCount(0);
      await page.getByTestId("book-doctor").first().click();
      await chooseSlot(page, "first");
      await page.evaluate(() => document.fonts.ready.then(() => undefined));
      await expectStepLabelsApart(page, '[data-testid="book-step"]');
      await expectNoHorizontalScroll(page);

      const summary = page.getByTestId("book-summary");
      await expect(summary.getByTestId("guest-fees")).toContainText(
        tr(lang, "portal:center.fees.text"),
      );
      if (size.width === 1280) {
        // From lg the summary sits beside the step (RTL: to its left) and stays on screen.
        const chooser = await page.getByTestId("slot-chooser").boundingBox();
        const side = await summary.boundingBox();
        expect(side && chooser && side.x + side.width <= chooser.x).toBe(true);
        expect(side?.y ?? -1).toBeGreaterThanOrEqual(0);
        // A plain row of buttons, no floating bar.
        await expect(page.getByTestId("book-action-bar")).toHaveCSS(
          "position",
          "static",
        );
      } else {
        await expect(page.getByTestId("book-action-bar")).toHaveCSS(
          "position",
          "sticky",
        );
      }
      await page.evaluate(() => {
        window.scrollTo(0, 0);
      });
      await snap(page, "patient-booking-unify-book");
      await page.getByTestId("book-next").click();
      await expect(page.getByTestId("book-review-step")).toBeVisible();
      await expectNoHorizontalScroll(page);
      await snap(page, "patient-booking-unify-review");
      await page.context().close();
    }
  });
});
