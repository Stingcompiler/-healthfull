/**
 * Appointments (FEATURES 2.5): book a free slot of the general practitioner tomorrow for a
 * patient file, then check the patient in, which opens the visit and its queue token.
 */
import { expect, test, type Page } from "@playwright/test";

import { createPatient, disposeApiClients, expectNoHorizontalScroll, login, setPrefs, tr, type Lang } from "../../helpers";

test.describe.configure({ timeout: 120_000 });
test.afterAll(disposeApiClients);

async function openDoctorTomorrow(page: Page, lang: Lang): Promise<void> {
  await page.goto("/appointments");
  await expect(page.locator("#main h1")).toHaveText(tr(lang, "visits:appointments.title"));
  await page.getByRole("combobox", { name: tr(lang, "visits:appointments.doctor") }).click();
  await page.getByRole("option", { name: lang === "ar" ? "د. أحمد الطيب" : "Dr. Ahmed Altayeb", exact: true }).click();
  await page.getByRole("button", { name: tr(lang, "visits:appointments.nextDay") }).first().click();
}

for (const v of [
  { lang: "en" as Lang, width: 1280, height: 800, theme: "dark" as const },
  { lang: "ar" as Lang, width: 375, height: 812, theme: "light" as const },
]) {
  test(`@patients book an appointment and check in (${v.lang}, ${String(v.width)}px)`, async ({ page }) => {
    const { patient } = await createPatient({ full_name_ar: "رحاب الصادق", full_name_en: "Rehab Alsadig", sex: "female" });
    await page.setViewportSize({ width: v.width, height: v.height });
    await setPrefs(page, { theme: v.theme, lang: v.lang });
    await login(page, "reception");
    await openDoctorTomorrow(page, v.lang);

    const slot = page.getByTestId("free-slot").first();
    await expect(slot).toBeVisible();
    await slot.getByRole("button").click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: tr(v.lang, "visits:appointments.bookTitle") })).toBeVisible();
    await dialog.getByRole("searchbox").fill(patient.file_no);
    await dialog.getByRole("button", { name: new RegExp(patient.file_no) }).click();
    await expect(dialog.getByTestId("picked-patient")).toContainText(patient.file_no);
    await dialog.getByRole("button", { name: tr(v.lang, "visits:appointments.book"), exact: true }).click();
    await expect(dialog).toHaveCount(0);

    const card = page.getByTestId("appointment").filter({ hasText: patient.file_no });
    await expect(card).toHaveAttribute("data-status", "booked");
    await expectNoHorizontalScroll(page);

    await card.getByRole("button", { name: tr(v.lang, "visits:appointments.checkIn") }).click();
    const checkIn = page.getByRole("dialog");
    await expect(checkIn.getByRole("heading", { name: tr(v.lang, "visits:appointments.checkInTitle") })).toBeVisible();
    await checkIn.getByRole("button", { name: tr(v.lang, "visits:appointments.checkIn") }).click();

    const slip = page.getByRole("dialog");
    await expect(slip.getByTestId("token-slip")).toContainText(patient.file_no);
    await slip.getByRole("button", { name: tr(v.lang, "common:actions.close") }).click();
    await expect(card).toHaveAttribute("data-status", "arrived");

    // The new visit is on the patient's file, linked to nothing else yet.
    await page.goto(`/patients/${String(patient.id)}`);
    await expect(page.getByTestId("visit-item").first()).toContainText(tr(v.lang, "visits:visitStatus.open"));
  });
}

test("@patients reschedule and cancel an appointment for a caller without a file", async ({ page }) => {
  await setPrefs(page, { theme: "warm", lang: "ar" });
  await login(page, "reception");
  await openDoctorTomorrow(page, "ar");
  await page.getByTestId("free-slot").first().getByRole("button").click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("tab", { name: tr("ar", "visits:appointments.forCaller") }).click();
  const caller = `متصل ${String(Date.now()).slice(-5)}`;
  await dialog.getByLabel(tr("ar", "visits:appointments.contactName")).fill(caller);
  await dialog.getByRole("button", { name: tr("ar", "visits:appointments.book"), exact: true }).click();
  const card = page.getByTestId("appointment").filter({ hasText: caller });
  await expect(card).toHaveAttribute("data-status", "booked");

  await card.getByRole("button", { name: tr("ar", "visits:appointments.moreFor", { name: caller }) }).click();
  await page.getByRole("menuitem", { name: tr("ar", "visits:appointments.reschedule") }).click();
  const move = page.getByRole("dialog");
  await move.getByRole("radio").last().click();
  await move.getByRole("button", { name: tr("ar", "visits:appointments.reschedule") }).click();
  await expect(move).toHaveCount(0);
  await expect(page.getByTestId("appointment").filter({ hasText: caller })).toHaveCount(2);

  const booked = page.locator('[data-testid="appointment"][data-status="booked"]').filter({ hasText: caller });
  await booked.getByRole("button", { name: tr("ar", "visits:appointments.moreFor", { name: caller }) }).click();
  await page.getByRole("menuitem", { name: tr("ar", "visits:appointments.cancel") }).click();
  const cancel = page.getByRole("dialog");
  await cancel.getByLabel(tr("ar", "visits:appointments.cancelReason")).fill("مسافر");
  await cancel.getByRole("button", { name: tr("ar", "visits:appointments.cancel") }).click();
  await expect(page.locator('[data-testid="appointment"][data-status="cancelled"]').filter({ hasText: caller })).toBeVisible();
});
