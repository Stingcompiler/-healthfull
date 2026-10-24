/**
 * The public center page at the portal's door: a signed-out phone visitor sees the center,
 * today's status, hours, doctors with clinic days, active notices and plain contact links, and
 * one repeated action that leads to sign-in. The administrator edits the page from
 * /administration/center-page (a notice, a hidden doctor) and the public page follows.
 */
import { expect, test } from "@playwright/test";

import { ADMIN_STATE } from "../../fixtures/state";
import { apiAs, expectNoHorizontalScroll, setPrefs, tr } from "../../helpers";
import { LANG, phonePage, portalPatient, signInPortal, t } from "./kit";

interface CenterPageSettings {
  hidden_doctor_ids: number[];
  [key: string]: unknown;
}

interface PublicPage {
  name_en: string;
  doctors: { id: number; name_en: string }[];
  announcements: { title_en: string }[];
}

test.describe("@portal center page", () => {
  test.describe.configure({ timeout: 120_000 });

  test("a signed-out visitor sees the center and one way in", async ({
    browser,
  }) => {
    const page = await phonePage(browser);
    const publicPage = (await (
      await page.context().request.get("/api/portal/center-page")
    ).json()) as PublicPage;
    await page.goto("/portal");
    const main = page.locator("#main");
    await expect(main.getByRole("heading", { level: 1 })).toHaveText(
      publicPage.name_en || t("appShortName"),
    );
    await expect(page.getByTestId("center-today")).toBeVisible();
    await expect(page.getByTestId("center-hours")).toBeVisible();
    await expect(page.getByTestId("center-doctor").first()).toBeVisible();
    await expect(page.getByTestId("center-announcement").first()).toBeVisible();
    // Contact links are plain links: a call and a WhatsApp chat, nothing fetched from outside.
    await expect(page.getByTestId("center-whatsapp")).toHaveAttribute(
      "href",
      /^https:\/\/wa\.me\/\d{8,15}$/,
    );
    // The one action, at the top and the end, plus the sticky header copy.
    const actions = page.getByTestId("center-sign-in");
    await expect(actions).toHaveCount(2);
    await expect(actions.first()).toHaveText(t("portal:center.signIn"));
    await expect(page.getByTestId("portal-header-sign-in")).toBeVisible();
    await expectNoHorizontalScroll(page);
    await actions.first().click();
    await expect(page).toHaveURL(/\/portal\/sign-in$/);
    await expect(page.getByTestId("portal-login")).toBeVisible();
    await expect(page.getByTestId("portal-header-sign-in")).toHaveCount(0);
  });

  test("a signed-in patient is offered their file instead", async ({
    browser,
  }) => {
    const who = await portalPatient();
    const page = await phonePage(browser);
    await signInPortal(page, who);
    await page.goto("/portal");
    const action = page.getByTestId("center-sign-in").first();
    await expect(action).toHaveText(t("portal:center.openFile"));
    await action.click();
    await expect(page).toHaveURL(/\/portal\/home$/);
  });

  test.describe("administration", () => {
    test.use({
      storageState: ADMIN_STATE,
      viewport: { width: 1280, height: 800 },
    });

    test("a notice and a hidden doctor reach the public page", async ({
      page,
      browser,
    }) => {
      const admin = await apiAs("admin");
      const before = await admin.get<CenterPageSettings>(
        "/api/core/center-page",
      );
      const title = `Notice ${String(Date.now())}`;
      try {
        await setPrefs(page, { theme: "light", lang: LANG });
        await page.goto("/administration/center-page");
        await expect(page.getByTestId("center-page-form")).toBeVisible();
        await page.getByTestId("announcement-add").click();
        const dialog = page.getByRole("dialog");
        await dialog
          .getByLabel(tr(LANG, "admin:centerPage.titleEn"))
          .fill(title);
        await dialog
          .getByRole("button", {
            name: tr(LANG, "admin:centerPage.saveAnnouncement"),
          })
          .click();
        await expect(dialog).toBeHidden();
        await expect(
          page.getByTestId("announcement-row").filter({ hasText: title }),
        ).toContainText(tr(LANG, "admin:centerPage.state.shown"));

        // Untick the first doctor and save the page.
        const visitor = await phonePage(browser);
        const shown = (await (
          await visitor.context().request.get("/api/portal/center-page")
        ).json()) as PublicPage;
        const doctor = shown.doctors[0];
        if (!doctor) throw new Error("the seed has doctors with clinic hours");
        const doctors = page.getByTestId("section-doctors");
        await doctors.getByRole("checkbox", { name: doctor.name_en }).uncheck();
        await page
          .getByRole("button", { name: tr(LANG, "admin:centerPage.save") })
          .click();
        await expect(
          page.getByText(tr(LANG, "admin:centerPage.saved")),
        ).toBeVisible();

        await visitor.goto("/portal");
        await expect(
          visitor.getByTestId("center-announcement").filter({ hasText: title }),
        ).toBeVisible();
        await expect(
          visitor.getByTestId("center-doctor").first(),
        ).toBeVisible();
        await expect(visitor.getByTestId("center-doctors")).not.toContainText(
          doctor.name_en,
        );
        await visitor.context().close();
      } finally {
        await admin.put("/api/core/center-page", before);
        const rows = await admin.get<{ id: number; title_en: string }[]>(
          "/api/core/announcements",
        );
        for (const row of rows.filter((r) => r.title_en === title)) {
          await admin.patch(`/api/core/announcements/${String(row.id)}`, {
            active: false,
          });
        }
      }
    });
  });
});
