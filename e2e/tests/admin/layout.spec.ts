/**
 * Administration layouts the route matrix does not open: the weekly schedule editor (a dialog)
 * and the permission matrix scrolled on both axes. At 375, 768 and 1280 in both languages the
 * schedule rows show the chosen day, room and full times, and the matrix keeps its role headers
 * and permission names in view.
 */
import { expect, test, type Locator, type Page } from "@playwright/test";

import { ADMIN_STATE } from "../../fixtures/state";
import { expectNoHorizontalScroll, LANGS, setPrefs, snap, tr, type Lang } from "../../helpers";

const VIEWPORTS = [
  { width: 375, height: 812 },
  { width: 768, height: 1024 },
  { width: 1280, height: 800 },
] as const;

async function width(locator: Locator): Promise<number> {
  const box = await locator.boundingBox();
  if (!box) throw new Error("element has no box");
  return box.width;
}

async function openSchedule(page: Page, lang: Lang): Promise<Locator> {
  await page.goto("/administration/departments");
  await page.getByRole("tab", { name: tr(lang, "admin:departments.doctorsTab") }).click();
  // The seeded doctor (seed_e2e) has a weekly schedule.
  const name = lang === "ar" ? "د. أحمد الطيب" : "Dr. Ahmed Altayeb";
  const row = page.locator("main").getByText(name).first();
  await expect(row).toBeVisible();
  // A table row from tablet width, a card on phones.
  await page
    .locator("main")
    .locator("tr, [data-slot=data-table-cards] > [role=listitem]")
    .filter({ hasText: name })
    .first()
    .getByRole("button", { name: tr(lang, "table.rowActions") })
    .click();
  await page.getByRole("menuitem", { name: tr(lang, "admin:departments.editSchedule") }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  // The title names the doctor in the UI language.
  await expect(dialog.getByRole("heading")).toContainText(name);
  return dialog;
}

for (const viewport of VIEWPORTS) {
  test.describe(`@admin layout ${String(viewport.width)}`, () => {
    test.use({ storageState: ADMIN_STATE, viewport });

    for (const lang of LANGS) {
      test(`schedule editor rows fit (${lang})`, async ({ page }) => {
        await setPrefs(page, { theme: "light", lang });
        const dialog = await openSchedule(page, lang);
        const session = dialog.getByTestId("session-0");
        await expect(session).toBeVisible();

        // The chosen weekday and room are readable, not squeezed to an arrow.
        const comboboxes = session.getByRole("combobox");
        await expect(comboboxes).toHaveCount(2);
        for (const box of await comboboxes.all()) {
          expect(await width(box)).toBeGreaterThanOrEqual(110);
          await expect(box).not.toHaveText("");
        }
        // Time inputs are wide enough for "02:00 PM" (the AM/PM marker is not cut off).
        for (const input of await session.locator("input[type=time]").all()) {
          expect(await width(input)).toBeGreaterThanOrEqual(110);
        }
        // Nothing sticks out of the dialog.
        const overflow = await dialog.evaluate((el) => el.scrollWidth - el.clientWidth);
        expect(overflow).toBeLessThanOrEqual(1);
        await expectNoHorizontalScroll(page);
        await snap(page, "admin-schedule-dialog");
      });
    }

    if (viewport.width >= 768) {
      test("permission matrix keeps role headers and permission names in view", async ({ page }) => {
        await setPrefs(page, { theme: "light", lang: "en" });
        await page.goto("/administration/roles");
        const matrix = page.getByTestId("permission-matrix");
        await expect(matrix).toBeVisible();
        const header = matrix.getByRole("columnheader", { name: tr("en", "roles.receptionist") });
        const permissionHeader = matrix.getByRole("columnheader", { name: tr("en", "admin:roles.permission") });

        // Scroll far down: the role headers stay at the top of the matrix.
        await matrix.evaluate((el) => {
          el.scrollTop = el.scrollHeight;
        });
        const top = (await matrix.boundingBox())?.y ?? 0;
        const headerBox = await header.boundingBox();
        expect(headerBox).not.toBeNull();
        expect(Math.abs((headerBox?.y ?? 0) - top)).toBeLessThanOrEqual(4);
        await expect(header).toBeInViewport();

        // Scroll to the end side: the permission column stays at the start.
        await matrix.evaluate((el) => {
          el.scrollLeft = el.scrollWidth;
        });
        await expect(permissionHeader).toBeInViewport();
        // Protected cells say why they are locked.
        await expect(matrix.getByTestId("perm-lock-admin-core.manage_roles")).toBeAttached();
        await expect(page.getByText(tr("en", "admin:roles.protectedHint"))).toBeVisible();
        await expectNoHorizontalScroll(page);
        await snap(page, "admin-roles-scrolled");
      });
    }
  });
}
