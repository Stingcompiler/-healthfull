/**
 * Guest booking (ADR 0029 D, F; plan Phase 4, screens of Phase 4b): a visitor without a patient
 * file books from the center page (doctor, day, time, name and phone, review with the fees and
 * the cancellation policy), solves the form check in the browser, and sees the reference and
 * the PIN once; then opens the booking with them, moves it and cancels it. A lost answer is
 * sent again with the same Idempotency-Key and gives the same booking. Wrong credentials read
 * the same whatever was wrong. The two public pages pass axe and have no horizontal scroll at
 * 375, 768 and 1280, and wear the center website's header and footer (D-0023): a stepper at
 * every width, the summary beside the step from lg, a floating action bar on phones, and a help
 * card beside the sign-in form from lg.
 *
 * The seed has guest booking on with approval off (bookings confirm at once) and a 14-bit form
 * check (apps/core/e2e/center_page.py).
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { ANONYMOUS_STATE } from "../../fixtures/state";
import {
  expectNoHorizontalScroll,
  setPrefs,
  snap,
  tr,
  trackConsoleErrors,
  type Lang,
} from "../../helpers";
import { bookAsGuest, phonePage, uniquePhone } from "./kit";

test.use({ storageState: ANONYMOUS_STATE });

async function chooseSlot(
  page: Page,
  which: "first" | "last" = "first",
): Promise<void> {
  await page.getByTestId("book-doctor").first().click();
  const day = page.getByTestId("book-day").last(); // the furthest day: past every cut-off
  await expect(day).toBeVisible();
  await day.click();
  const slot =
    which === "first"
      ? page.getByTestId("book-slot").first()
      : page.getByTestId("book-slot").last();
  await expect(slot).toBeVisible();
  await slot.click();
}

async function fillContact(
  page: Page,
  lang: Lang,
  phone: string,
): Promise<void> {
  const form = page.getByTestId("guest-contact");
  // By role: the step's card is named "Your name and phone" too.
  await form
    .getByRole("textbox", { name: tr(lang, "portal:guest.form.name") })
    .fill("Amna Guest");
  await form
    .getByRole("textbox", { name: tr(lang, "portal:guest.form.phone") })
    .fill(phone);
  await page.getByTestId("guest-next-review").click();
}

test.describe("@guest-booking", () => {
  test.describe.configure({ timeout: 180_000 });

  test("a visitor books without a file, keeps the reference and PIN, then opens, moves and cancels it (375, ar)", async ({
    browser,
  }) => {
    const lang: Lang = "ar";
    const page = await phonePage(browser, 375);
    await setPrefs(page, { theme: "light", lang });
    const logged = trackConsoleErrors(page, { allowAnonymousMe: true });

    // The center page offers "Book online" to a visitor.
    await page.goto("/portal");
    await expect(page.getByTestId("center-page")).toBeVisible();
    await expect(page.getByTestId("center-sticky-book")).toBeVisible();
    await page.getByTestId("center-book").click();
    await expect(page).toHaveURL(/\/portal\/book$/);
    await expect(page.getByTestId("guest-patient-sign-in")).toBeVisible();

    // Step 1: doctor, day, time. The stepper shows the open step; day and time appear only once
    // they can be chosen (no "choose a doctor first" placeholders).
    await expect(page.getByTestId("book-doctor").first()).toBeVisible();
    await expect(
      page.getByTestId("guest-step").locator('[aria-current="step"]'),
    ).toContainText(tr(lang, "portal:guest.steps.slot"));
    await expect(page.getByTestId("book-day")).toHaveCount(0);
    await expect(page.getByTestId("book-slot")).toHaveCount(0);
    await expect(
      page.getByText(tr(lang, "portal:book.chooseDoctorFirst")),
    ).toHaveCount(0);
    await expect(page.getByTestId("guest-next-contact")).toBeDisabled();
    await chooseSlot(page);
    // The phone's action bar floats within the screen while the step scrolls.
    const next = await page.getByTestId("guest-next-contact").boundingBox();
    expect((next?.y ?? 9999) + (next?.height ?? 0)).toBeLessThanOrEqual(812);
    await expect(page.getByTestId("guest-action-bar")).toContainText(
      tr(lang, "portal:guest.next"),
    );
    await expectNoHorizontalScroll(page);
    await snap(page, "guest-book-1-slot");
    await page.evaluate(() => {
      window.scrollTo(0, 0);
    });
    await snap(page, "guest-redesign-book-step1");
    await page.getByTestId("guest-next-contact").click();
    await expect(
      page.getByTestId("guest-step").locator('[aria-current="step"]'),
    ).toContainText(tr(lang, "portal:guest.steps.contact"));

    // Step 2: name and phone, checked before anything is sent.
    await page.getByTestId("guest-next-review").click();
    await expect(
      page.getByText(tr(lang, "portal:guest.form.nameRequired")),
    ).toBeVisible();
    await expect(
      page.getByText(tr(lang, "portal:guest.form.phoneInvalid")),
    ).toBeVisible();
    await snap(page, "guest-book-2-contact");
    await fillContact(page, lang, uniquePhone());

    // Step 3: review with "fees are paid at reception" and the cancellation policy.
    const review = page.getByTestId("guest-review-step");
    await expect(review).toBeVisible();
    await expect(review.getByTestId("guest-fees")).toContainText(
      tr(lang, "portal:center.fees.text"),
    );
    await expect(review).toContainText("Amna Guest");
    await expectNoHorizontalScroll(page);
    await snap(page, "guest-book-3-review");

    const posts: string[] = [];
    page.on("request", (r) => {
      if (
        r.method() === "POST" &&
        r.url().endsWith("/api/portal/guest-bookings")
      ) {
        posts.push(r.headers()["idempotency-key"] ?? "");
      }
    });
    await page.getByTestId("guest-submit").click();

    // The confirmation: reference and PIN once, a WhatsApp share without the PIN, print.
    const confirmation = page.getByTestId("guest-confirmation");
    await expect(confirmation).toBeVisible({ timeout: 60_000 });
    const reference = (
      await page.getByTestId("guest-reference").innerText()
    ).trim();
    const pin = (await page.getByTestId("guest-pin").innerText()).trim();
    expect(reference).toMatch(/^[A-Z2-7]{5}-[A-Z2-7]{5}$/);
    expect(pin).toMatch(/^\d{6}$/);
    expect(posts).toHaveLength(1);
    expect(posts[0]).toMatch(/^[0-9a-f-]{36}$/);
    await expect(confirmation).toContainText(
      tr(lang, "portal:guest.done.saveTitle"),
    );
    const share = page.getByTestId("guest-share");
    const href = (await share.getAttribute("href")) ?? "";
    expect(href.startsWith("https://wa.me/?text=")).toBe(true);
    expect(decodeURIComponent(href)).toContain(reference);
    expect(decodeURIComponent(href)).not.toContain(pin);
    await expect(page.getByTestId("guest-print")).toBeVisible();
    await expect(page.getByTestId("guest-status")).toHaveText(
      tr(lang, "portal:appointments.display.confirmed"),
    );
    await expect(
      page.getByTestId("guest-step").locator('[data-state="done"]'),
    ).toHaveCount(4);
    await expectNoHorizontalScroll(page);
    await snap(page, "guest-book-4-confirmation");
    await snap(page, "guest-redesign-book-confirm");

    // Open the booking with the reference (typed loosely) and the PIN.
    await page.getByTestId("guest-done-open").click();
    await expect(page).toHaveURL(/\/portal\/booking$/);
    const signIn = page.getByTestId("guest-sign-in");
    await signIn
      .getByLabel(tr(lang, "portal:guest.reference"))
      .fill(reference.toLowerCase().replace("-", " "));
    await signIn.getByLabel(tr(lang, "portal:guest.pin")).fill(pin);
    await signIn
      .getByRole("button", { name: tr(lang, "portal:guest.signIn.submit") })
      .click();
    const view = page.getByTestId("guest-view");
    await expect(view).toBeVisible();
    await expect(view).toContainText(reference);
    const before = (await page.getByTestId("guest-time").innerText()).trim();
    await expectNoHorizontalScroll(page);
    await snap(page, "guest-booking-view");

    // Move it to the last free time of the furthest day.
    await page.getByTestId("guest-reschedule").click();
    await expect(page.getByTestId("guest-reschedule-picker")).toBeVisible();
    await expect(page.getByTestId("book-doctor").first()).toHaveAttribute(
      "aria-checked",
      "true",
    );
    const day = page.getByTestId("book-day").last();
    await day.click();
    await page.getByTestId("book-slot").last().click();
    await page.getByTestId("guest-reschedule-confirm").click();
    await expect(page.getByText(tr(lang, "portal:book.moved"))).toBeVisible();
    await expect(page.getByTestId("guest-time")).not.toHaveText(before);
    await expect(page.getByTestId("guest-status")).toHaveText(
      tr(lang, "portal:appointments.display.confirmed"),
    );

    // Cancel it: the reference keeps showing the cancelled booking.
    await page.getByTestId("guest-cancel").click();
    await page
      .getByRole("button", {
        name: tr(lang, "portal:appointments.cancelConfirm"),
      })
      .click();
    await expect(page.getByTestId("guest-status")).toHaveText(
      tr(lang, "portal:appointments.display.cancelled_by_you"),
    );
    await expect(page.getByTestId("guest-no-actions")).toBeVisible();

    await page.getByTestId("guest-sign-out").click();
    await expect(page.getByTestId("guest-sign-in")).toBeVisible();
    expect(logged.errors(), "console errors / page errors").toEqual([]);
    await page.context().close();
  });

  test("a lost answer is sent again with the same Idempotency-Key and gives the same booking", async ({
    browser,
  }) => {
    const page = await phonePage(browser, 375);
    const keys: string[] = [];
    let first = true;
    await page.route("**/api/portal/guest-bookings", async (route) => {
      keys.push(route.request().headers()["idempotency-key"] ?? "");
      if (first) {
        first = false;
        await route.fetch(); // the server books it ...
        await route.abort("connectionreset"); // ... and the answer is lost on the way back
        return;
      }
      await route.continue();
    });
    await page.goto("/portal/book");
    await chooseSlot(page);
    await page.getByTestId("guest-next-contact").click();
    await fillContact(page, "en", uniquePhone());
    await page.getByTestId("guest-submit").click();
    await expect(
      page.getByText(tr("en", "portal:guest.retryHint")),
    ).toBeVisible({ timeout: 60_000 });

    // A reload keeps the unanswered attempt; sending it again gets the stored answer.
    await page.reload();
    await expect(page.getByTestId("guest-resume")).toBeVisible();
    await page.getByTestId("guest-resume-send").click();
    await expect(page.getByTestId("guest-confirmation")).toBeVisible({
      timeout: 60_000,
    });
    await expect(page.getByTestId("guest-pin")).toHaveText(/^\d{6}$/);
    expect(keys).toHaveLength(2);
    expect(keys[1]).toBe(keys[0]);
    await page.context().close();
  });

  test("a wrong PIN and an unknown reference read the same, with the way out through reception", async ({
    browser,
  }) => {
    const page = await phonePage(browser, 375);
    const { created } = await bookAsGuest(page.context().request);
    await page.goto("/portal/booking");
    const form = page.getByTestId("guest-sign-in");
    const attempt = async (reference: string, pin: string): Promise<string> => {
      await form.getByLabel(tr("en", "portal:guest.reference")).fill(reference);
      await form.getByLabel(tr("en", "portal:guest.pin")).fill(pin);
      await form
        .getByRole("button", { name: tr("en", "portal:guest.signIn.submit") })
        .click();
      const error = page.getByTestId("guest-sign-in-error");
      await expect(error).toBeVisible();
      return (await error.innerText()).trim();
    };
    const wrongPin = await attempt(
      created.reference,
      created.pin === "000000" ? "111111" : "000000",
    );
    const unknown = await attempt("AAAAA-AAAAA", "123456");
    expect(wrongPin).toBe(unknown);
    expect(wrongPin).toContain(tr("en", "errors:GUEST_INVALID_CREDENTIALS"));
    expect(wrongPin).toContain(tr("en", "portal:guest.signIn.lockedHint"));
    await page.context().close();
  });

  test("from lg the step sits beside a sticky summary; the website header and footer frame both pages (1280, ar)", async ({
    browser,
  }) => {
    const lang: Lang = "ar";
    const page = await phonePage(browser, 1280);
    await page.setViewportSize({ width: 1280, height: 800 });
    await setPrefs(page, { theme: "light", lang });
    await page.goto("/portal/book");
    await expect(page.getByTestId("book-doctor").first()).toBeVisible();
    // The center website's header brand and footer, with the vendor line.
    await expect(page.getByTestId("portal-brand")).toBeVisible();
    const footer = page.getByTestId("center-footer");
    await expect(footer.getByTestId("footer-powered-by")).toHaveAttribute(
      "href",
      "https://stingdev.pro",
    );
    await expect(footer.getByTestId("footer-policies")).toHaveAttribute(
      "href",
      "/portal#center-policies",
    );
    // The other ways in are one quiet line, not cards above the task.
    await expect(page.getByTestId("guest-entry-links")).toBeVisible();
    await expect(page.getByTestId("guest-open-booking")).toHaveAttribute(
      "href",
      "/portal/booking",
    );

    const summary = page.getByTestId("book-summary");
    await expect(summary).toContainText(tr(lang, "portal:guest.summary.empty"));
    await chooseSlot(page);
    // The summary names the choice, beside the step (RTL: to its left).
    const chooser = await page.getByTestId("slot-chooser").boundingBox();
    const side = await summary.boundingBox();
    expect(side && chooser && side.x + side.width <= chooser.x).toBe(true);
    // Sticky: after choosing a time far down the step, the summary is still on screen.
    expect(side?.y ?? -1).toBeGreaterThanOrEqual(0);
    expect((side?.y ?? 9999) + (side?.height ?? 0)).toBeLessThanOrEqual(800);
    await expect(summary.getByTestId("guest-fees")).toContainText(
      tr(lang, "portal:center.fees.text"),
    );
    await expectNoHorizontalScroll(page);
    await page.evaluate(() => {
      window.scrollTo(0, 0);
    });
    await snap(page, "guest-redesign-book-step1");

    await page.getByTestId("guest-next-contact").click();
    await fillContact(page, lang, uniquePhone());
    await expect(page.getByTestId("guest-review-step")).toBeVisible();
    await expectNoHorizontalScroll(page);
    await page.evaluate(() => {
      window.scrollTo(0, 0);
    });
    await snap(page, "guest-redesign-book-review");

    // /portal/booking: the form beside the help card.
    await page.goto("/portal/booking");
    const form = page.getByTestId("guest-sign-in");
    const help = page.getByTestId("guest-sign-in-help");
    await expect(form).toBeVisible();
    await expect(help).toContainText(
      tr(lang, "portal:guest.signIn.whereTitle"),
    );
    await expect(help.getByTestId("guest-forgot-pin")).toContainText(
      tr(lang, "portal:guest.signIn.forgotText"),
    );
    await expect(help.getByTestId("guest-book-new")).toHaveAttribute(
      "href",
      "/portal/book",
    );
    const formBox = await form.boundingBox();
    const helpBox = await help.boundingBox();
    expect(helpBox && formBox && helpBox.x + helpBox.width <= formBox.x).toBe(
      true,
    );
    await expect(page.getByTestId("center-footer")).toBeVisible();
    await expectNoHorizontalScroll(page);
    await snap(page, "guest-redesign-booking-signin");
    await page.context().close();
  });

  test("the booking pages at 768 and on a phone (ar), and the opened booking at 1280 (dark, en)", async ({
    browser,
  }) => {
    const tablet = await phonePage(browser, 768);
    await tablet.setViewportSize({ width: 768, height: 1024 });
    await setPrefs(tablet, { theme: "light", lang: "ar" });
    await tablet.goto("/portal/book");
    await chooseSlot(tablet);
    await expect(tablet.getByTestId("guest-step")).toBeVisible();
    await expectNoHorizontalScroll(tablet);
    await tablet.evaluate(() => {
      window.scrollTo(0, 0);
    });
    await snap(tablet, "guest-redesign-book-step1");
    await tablet.context().close();

    const phone = await phonePage(browser, 375);
    await setPrefs(phone, { theme: "light", lang: "ar" });
    await phone.goto("/portal/booking");
    await expect(phone.getByTestId("guest-sign-in")).toBeVisible();
    await expect(phone.getByTestId("guest-sign-in-help")).toBeVisible();
    await expectNoHorizontalScroll(phone);
    await snap(phone, "guest-redesign-booking-signin");
    await phone.context().close();

    const page = await phonePage(browser, 1280);
    await page.setViewportSize({ width: 1280, height: 800 });
    await setPrefs(page, { theme: "dark", lang: "en" });
    const { created } = await bookAsGuest(page.context().request);
    await page.goto("/portal/booking");
    const form = page.getByTestId("guest-sign-in");
    await form
      .getByLabel(tr("en", "portal:guest.reference"))
      .fill(created.reference);
    await form.getByLabel(tr("en", "portal:guest.pin")).fill(created.pin ?? "");
    await form
      .getByRole("button", { name: tr("en", "portal:guest.signIn.submit") })
      .click();
    await expect(page.getByTestId("guest-view")).toContainText(
      created.reference,
    );
    await expect(page.getByTestId("guest-reschedule")).toBeVisible();
    await expect(page.getByTestId("guest-cancel")).toBeVisible();
    await expectNoHorizontalScroll(page);
    await snap(page, "guest-redesign-booking-view");
    await page.context().close();
  });

  for (const size of [
    { width: 375, height: 812 },
    { width: 768, height: 1024 },
    { width: 1280, height: 800 },
  ]) {
    test(`the public booking pages fit and pass axe at ${String(size.width)}px`, async ({
      browser,
    }) => {
      const page = await phonePage(browser, size.width);
      await page.setViewportSize(size);
      for (const [path, ready] of [
        ["/portal/book", "book-doctor"],
        ["/portal/booking", "guest-sign-in"],
      ] as const) {
        await page.goto(path);
        await expect(page.getByTestId(ready).first()).toBeVisible();
        await expectNoHorizontalScroll(page);
        const axe = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
          .analyze();
        expect(
          axe.violations.map(
            (v) =>
              `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
          ),
          `${path} axe`,
        ).toEqual([]);
      }
      await page.context().close();
    });
  }
});
