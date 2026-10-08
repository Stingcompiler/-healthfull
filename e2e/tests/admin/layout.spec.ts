/**
 * Administration layouts the route matrix does not open: the weekly schedule editor (a dialog)
 * and the permission matrix scrolled on both axes. At 375, 768 and 1280 in both languages the
 * schedule rows show the chosen day, room and full 24-hour times, and the matrix keeps its role
 * headers, permission names and module labels in view. The payers table and the center profile
 * fit their cards.
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
        // Times are 24-hour HH:MM in both languages (no browser-locale AM/PM), shown in full.
        for (const key of ["admin:departments.start", "admin:departments.end"]) {
          const input = session.getByLabel(tr(lang, key));
          await expect(input).toHaveValue(/^([01]\d|2[0-3]):[0-5]\d$/);
          expect(await width(input)).toBeGreaterThanOrEqual(80);
        }
        // Each session is a named group and its delete button says which session it removes.
        const day = (await session.getByRole("combobox").first().textContent()) ?? "";
        await expect(session).toHaveAttribute("role", "group");
        await expect(session).toHaveAttribute("aria-label", new RegExp(day.trim()));
        const remove = session.getByRole("button", { name: new RegExp(day.trim()) });
        await expect(remove).toHaveCount(1);
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
        // The module label of a block of permissions stays in view however far it is scrolled.
        const group = matrix.locator("[data-testid^=matrix-group-]").last();
        await group.evaluate((node) => {
          const scroller = node.closest("[data-testid=permission-matrix]");
          const row = node.closest("tr");
          if (scroller instanceof HTMLElement && row) scroller.scrollTop = row.offsetTop - 60;
        });
        await expect(group).toBeInViewport();
        await expect(group).not.toHaveText("");
        // One tab stop for the whole matrix; arrow keys move between cells.
        await expect(matrix.locator("[data-row][tabindex='0']")).toHaveCount(1);
        const cell = matrix.locator("[data-row='0'][data-col='1']");
        await cell.focus();
        await page.keyboard.press("ArrowDown");
        await expect(matrix.locator("[data-row='1'][data-col='1']")).toBeFocused();
        await page.keyboard.press("ArrowRight");
        await expect(matrix.locator("[data-row='1'][data-col='2']")).toBeFocused();
        // Protected cells say why they are locked.
        await expect(matrix.getByTestId("perm-lock-admin-core.manage_roles")).toBeAttached();
        await expect(page.getByText(tr("en", "admin:roles.protectedHint"))).toBeVisible();
        await expectNoHorizontalScroll(page);
        await snap(page, "admin-roles-scrolled");
      });
    }

    test("payers table and center profile fit their cards (en)", async ({ page }) => {
      await setPrefs(page, { theme: "light", lang: "en" });
      await page.goto("/administration/payers");
      const table = page.locator("main [data-mode]").first();
      await expect(page.locator("main").getByText("AMAN").first()).toBeVisible();
      if ((await table.getAttribute("data-mode")) === "table") {
        // The last column ends inside the card: nothing is cut off at the end side.
        const box = await table.boundingBox();
        const last = await table.locator("thead th:visible").last().boundingBox();
        expect(box && last).toBeTruthy();
        if (box && last) expect(last.x + last.width).toBeLessThanOrEqual(box.x + box.width + 1);
        const hidden = await table.evaluate((el) => {
          const scroller = el.querySelector("table")?.parentElement;
          return scroller ? scroller.scrollWidth - scroller.clientWidth : 0;
        });
        expect(hidden).toBeLessThanOrEqual(1);
      }
      await expectNoHorizontalScroll(page);
      await snap(page, "admin-payers-fit");

      await page.goto("/administration/settings");
      // Phone, registration and tax numbers have room for their values.
      for (const key of ["admin:settings.phone", "admin:settings.registrationNo", "admin:settings.taxNo"]) {
        expect(await width(page.getByLabel(tr("en", key)))).toBeGreaterThanOrEqual(150);
      }
      await expectNoHorizontalScroll(page);
    });
  });
}
