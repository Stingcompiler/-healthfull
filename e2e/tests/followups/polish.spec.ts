/**
 * Phase 8 polish: every role reaches its screens from the navigation (no typed URLs), and the
 * doctor closes a visit («ختم الزيارة») once the patient left the queue.
 * Filter with `make e2e E2E_GREP=@polish`.
 */
import { expect, type Page, test } from "@playwright/test";

import { ANONYMOUS_STATE } from "../../fixtures/state";
import {
  apiAs,
  disposeApiClients,
  expectNoHorizontalScroll,
  login,
  paidVisit,
  snap,
  trackConsoleErrors,
} from "../../helpers";

test.describe.configure({ timeout: 150_000 });
test.use({ storageState: ANONYMOUS_STATE });
test.afterAll(disposeApiClients);

async function openFromNav(page: Page, id: string, path: RegExp): Promise<void> {
  const item = page.getByTestId(`nav-${id}`).first();
  await expect(item).toBeVisible();
  await item.click();
  await expect(page).toHaveURL(path);
}

test.describe("@polish nav reach", () => {
  test("a cashier opens the walk-in sale from the navigation", async ({ page }) => {
    const logged = trackConsoleErrors(page, { allowAnonymousMe: true });
    await page.setViewportSize({ width: 1280, height: 800 });
    await login(page, "cashier");
    await expect(page.getByTestId("nav-pharmacy")).toHaveCount(0);
    await openFromNav(page, "walk-in-sale", /\/pharmacy\/sale$/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.setViewportSize({ width: 375, height: 812 });
    await expectNoHorizontalScroll(page);
    expect(logged.errors()).toEqual([]);
  });

  test("reception opens the bed board and approved lab results", async ({ page }) => {
    const logged = trackConsoleErrors(page, { allowAnonymousMe: true });
    await page.setViewportSize({ width: 1280, height: 800 });
    await login(page, "reception");
    await expect(page.getByTestId("nav-nursing")).toHaveCount(0);
    await expect(page.getByTestId("nav-lab")).toHaveCount(0);
    await openFromNav(page, "bed-board", /\/nursing\/beds$/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await openFromNav(page, "lab-approved", /\/lab\/approved-results$/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    for (const width of [375, 768]) {
      await page.setViewportSize({ width, height: 900 });
      await expectNoHorizontalScroll(page);
    }
    await snap(page, "polish-reception-lab-results");
    expect(logged.errors()).toEqual([]);
  });

  test("a nurse collects a sample from the navigation and has no doctor's clinic", async ({ page }) => {
    const logged = trackConsoleErrors(page, { allowAnonymousMe: true });
    await page.setViewportSize({ width: 1280, height: 800 });
    await login(page, "nurse");
    await expect(page.getByTestId("nav-clinic")).toHaveCount(0);
    await openFromNav(page, "lab-collect", /\/lab\/collect$/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.setViewportSize({ width: 375, height: 812 });
    await expectNoHorizontalScroll(page);
    await snap(page, "polish-nurse-collection");
    expect(logged.errors()).toEqual([]);
  });
});

test.describe("@polish visit close", () => {
  test("the doctor closes the visit after finishing the consultation", async ({ page }) => {
    const logged = trackConsoleErrors(page, { allowAnonymousMe: true });
    const visit = await paidVisit({
      doctor: "doctor",
      patient_fields: { full_name_en: "Mustafa Idris Polish" },
    });
    const entry = visit.queue_entry;
    if (!entry) throw new Error("the paid visit has no queue entry");
    const doctor = await apiAs("doctor");
    for (const action of ["call", "start", "complete"]) {
      await doctor.post(`/api/clinical/worklist/${String(entry.id)}/action`, { action });
    }

    await page.setViewportSize({ width: 1280, height: 800 });
    await login(page, "doctor");
    await page.goto(`/clinic/visits/${String(visit.visit.id)}`);
    const close = page.getByTestId("visit-close");
    await expect(close).toBeVisible();
    await close.click();
    await page.getByRole("alertdialog").getByRole("button", { name: /close visit|ختم الزيارة/i }).click();
    await expect(close).toHaveCount(0);
    const detail = await doctor.get<{ visit: { status: string } }>(`/api/visits/${String(visit.visit.id)}`);
    expect(detail.visit.status).toBe("closed");
    await page.setViewportSize({ width: 375, height: 812 });
    await expectNoHorizontalScroll(page);
    await snap(page, "polish-visit-closed");
    expect(logged.errors()).toEqual([]);
  });

  test("the server refuses closing while the patient is in the queue", async () => {
    const visit = await paidVisit({ doctor: "doctor" });
    const doctor = await apiAs("doctor");
    const refused = await doctor.post<{ code: string }>(
      `/api/visits/${String(visit.visit.id)}/close`,
      {},
      { expect: 409 },
    );
    expect(refused.code).toBe("VISIT_IN_QUEUE");
    const reception = await apiAs("reception");
    const denied = await reception.post<{ code: string }>(
      `/api/visits/${String(visit.visit.id)}/close`,
      {},
      { expect: 403 },
    );
    expect(denied.code).toBe("PERMISSION_DENIED");
  });
});
