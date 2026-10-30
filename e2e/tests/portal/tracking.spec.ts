/**
 * Patient tracking (public site Phase 5; plan section 5, ADR 0029 I): a visit's timeline in the
 * patient's words and the portal inbox with its unread badge. A patient opens only their own
 * visit; the inbox marks read one by one or all at once. Both screens and the appointments page
 * (which lists the visits) fit 375, 768 and 1280 with no horizontal scroll and pass axe.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { csrfHeaders, expectNoHorizontalScroll } from "../../helpers";
import { phonePage, portalPatient, signInPortal, t } from "./kit";

test.describe("@portal @tracking patient tracking", () => {
  test.describe.configure({ timeout: 120_000 });

  test("the timeline shows each step in the patient's words; another patient's visit is not found", async ({
    browser,
  }) => {
    const [mine, theirs] = await Promise.all([
      portalPatient(),
      portalPatient(),
    ]);
    const page = await phonePage(browser);
    await signInPortal(page, mine);

    // From the appointments page: the visit list opens the timeline.
    await page.goto("/portal/appointments");
    const row = page.getByTestId("visit-row");
    await expect(row).toHaveCount(1);
    await row.first().click();
    await expect(page).toHaveURL(
      new RegExp(`/portal/visits/${String(mine.visit.id)}$`),
    );

    const timeline = page.getByTestId("visit-timeline");
    await expect(timeline).toBeVisible();
    await expect(page.getByTestId("visit-status")).toHaveText(
      t("portal:timeline.visit.at_center"),
    );
    const approved = timeline.locator(
      `[data-testid="timeline-order"][data-line="${String(mine.approved_line)}"]`,
    );
    await expect(approved).toHaveAttribute("data-status", "result_published");
    await expect(approved).toContainText(
      t("portal:timeline.order.result_published"),
    );
    // The malaria result waits for the supervisor: in progress, nothing to open.
    const draft = timeline.locator(
      `[data-testid="timeline-order"][data-line="${String(mine.draft_line)}"]`,
    );
    await expect(draft).toHaveAttribute("data-status", "in_progress");
    await expect(draft.getByTestId("timeline-open-result")).toHaveCount(0);
    await expect(timeline.getByTestId("timeline-invoice")).toHaveAttribute(
      "data-status",
      "paid",
    );

    await approved.getByTestId("timeline-open-result").click();
    await expect(page.getByTestId("result-values")).toBeVisible();

    // Someone else's visit: the server answers 404 and the screen says so.
    const response = await page
      .context()
      .request.get(`/api/portal/visits/${String(theirs.visit.id)}/timeline`);
    expect(response.status()).toBe(404);
    await page.goto(`/portal/visits/${String(theirs.visit.id)}`);
    await expect(page.getByText(t("errors:NOT_FOUND")).first()).toBeVisible();
    await expect(page.getByTestId("visit-timeline")).toHaveCount(0);
    await page.context().close();
  });

  test("the inbox badge counts unread notices; reading clears it", async ({
    browser,
  }) => {
    const [mine, theirs] = await Promise.all([
      portalPatient({ appointment: true }),
      portalPatient(),
    ]);
    const page = await phonePage(browser);
    await signInPortal(page, mine);
    await page.goto("/portal/home");

    // The CBC approval and the booking each wrote one notice.
    const badge = page.getByTestId("portal-notices-badge");
    await expect(badge).toHaveText("2");
    await page.getByTestId("portal-notices-bell").click();
    await expect(page).toHaveURL(/\/portal\/notices$/);
    const rows = page.getByTestId("notice-row");
    await expect(rows).toHaveCount(2);
    await expect(
      page.locator('[data-testid="notice-row"][data-kind="result_published"]'),
    ).toContainText(t("portal:notices.kind.result_published"));
    await expect(
      page.locator('[data-testid="notice-row"][data-kind="booking_confirmed"]'),
    ).toContainText(t("portal:notices.kind.booking_confirmed"));

    // Opening the result marks that notice read.
    await page
      .locator('[data-testid="notice-row"][data-kind="result_published"]')
      .getByTestId("notice-open")
      .click();
    await expect(page.getByTestId("result-values")).toBeVisible();
    await expect(badge).toHaveText("1");

    await page.getByTestId("portal-notices-bell").click();
    await page.getByTestId("notices-mark-all").click();
    await expect(badge).toHaveCount(0);
    await expect(
      page.locator('[data-testid="notice-row"][data-unread="true"]'),
    ).toHaveCount(0);

    // Another patient's notice cannot be touched.
    const other = await page
      .context()
      .request.post(`/api/portal/notices/${String(theirs.notice_id)}/read`, {
        headers: await csrfHeaders(page.context()),
      });
    expect(other.status()).toBe(404);
    await page.context().close();
  });

  for (const size of [
    { width: 375, height: 812 },
    { width: 768, height: 1024 },
    { width: 1280, height: 800 },
  ]) {
    test(`the tracking screens fit and pass axe at ${String(size.width)}px`, async ({
      browser,
    }) => {
      const who = await portalPatient({ appointment: true });
      const page = await phonePage(browser, size.width);
      await page.setViewportSize(size);
      await signInPortal(page, who);
      for (const [path, ready] of [
        [`/portal/visits/${String(who.visit.id)}`, "visit-timeline"],
        ["/portal/notices", "notices-list"],
        ["/portal/appointments", "visits-list"],
      ] as const) {
        await page.goto(path);
        await expect(page.getByTestId(ready)).toBeVisible();
        await page.waitForLoadState("networkidle");
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
