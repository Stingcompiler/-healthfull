/**
 * Registration (FEATURES 1.1-1.3): register in Arabic and English at three viewports, the
 * duplicate warning, and emergency registration completed later.
 */
import { expect, test, type Page } from "@playwright/test";

import {
  createPatient,
  disposeApiClients,
  expectNoHorizontalScroll,
  login,
  setPrefs,
  tr,
  type Lang,
} from "../../helpers";

test.describe.configure({ timeout: 90_000 });
test.afterAll(disposeApiClients);

async function signIn(page: Page, lang: Lang, theme: "light" | "dark" | "warm"): Promise<void> {
  await login(page, "reception");
  await setPrefs(page, { theme, lang });
}

function uniquePhone(): string {
  return `09${String(Date.now()).slice(-8)}`;
}

async function openNewPatient(page: Page, lang: Lang): Promise<void> {
  await page.goto("/patients");
  await expect(page.locator("#main h1")).toHaveText(tr(lang, "patients:title"));
  await page.getByRole("link", { name: tr(lang, "patients:new.open") }).first().click();
  await expect(page.locator("#main h1")).toHaveText(tr(lang, "patients:new.title"));
}

const CASES: { lang: Lang; width: number; height: number; nameAr: string; nameEn: string }[] = [
  { lang: "ar", width: 375, height: 812, nameAr: "عائشة محمد الحسن", nameEn: "" },
  { lang: "en", width: 1280, height: 800, nameAr: "", nameEn: "Mohamed Osman Babiker" },
  { lang: "ar", width: 768, height: 1024, nameAr: "إبراهيم عبدالرحيم", nameEn: "Ibrahim Abdelrahim" },
];

for (const c of CASES) {
  test(`@patients register a patient (${c.lang}, ${String(c.width)}px)`, async ({ page }) => {
    await page.setViewportSize({ width: c.width, height: c.height });
    await signIn(page, c.lang, c.lang === "ar" ? "light" : "dark");
    await openNewPatient(page, c.lang);

    if (c.nameAr) await page.getByLabel(tr(c.lang, "patients:form.nameAr")).fill(c.nameAr);
    if (c.nameEn) await page.getByLabel(tr(c.lang, "patients:form.nameEn")).fill(c.nameEn);
    await page.getByRole("radio", { name: tr(c.lang, "common:sex.female") }).check();
    await page.getByLabel(tr(c.lang, "patients:form.dateOfBirth")).fill("1988-03-14");
    await page.getByLabel(tr(c.lang, "patients:form.phone"), { exact: true }).fill(uniquePhone());
    await expectNoHorizontalScroll(page);
    await page.getByRole("button", { name: tr(c.lang, "patients:new.submit") }).click();

    await expect(page).toHaveURL(/\/patients\/\d+$/);
    await expect(page.locator("#main h1")).toHaveText(c.lang === "ar" ? c.nameAr || c.nameEn : c.nameEn || c.nameAr);
    await expect(page.locator('[data-slot="patient-card"]')).toContainText(/PT-\d{4}-\d+/);
    await expectNoHorizontalScroll(page);
  });
}

test("@patients duplicate warning offers the existing file", async ({ page }) => {
  const phone = uniquePhone();
  const { patient: existing } = await createPatient({ full_name_ar: "حسن الطاهر", phone, sex: "male" });
  await signIn(page, "en", "light");
  await openNewPatient(page, "en");

  await page.getByLabel(tr("en", "patients:form.nameEn")).fill("Hassan Altahir");
  await page.getByRole("radio", { name: tr("en", "common:sex.male") }).check();
  await page.getByLabel(tr("en", "patients:form.phone"), { exact: true }).fill(phone);
  const inline = page.getByText(tr("en", "patients:duplicates.inlineTitle_one", { count: "1" }));
  await expect(inline).toBeVisible();

  await page.getByRole("button", { name: tr("en", "patients:new.submit") }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: tr("en", "patients:duplicates.title") })).toBeVisible();
  await expect(dialog).toContainText(existing.file_no);
  await expect(dialog).toContainText(tr("en", "patients:duplicates.reason.phone"));

  // Same person: open the existing file instead of registering again.
  await dialog.getByRole("link", { name: tr("en", "patients:duplicates.openFile") }).click();
  await expect(page).toHaveURL(new RegExp(`/patients/${String(existing.id)}$`));
});

test("@patients duplicate warning can be overridden for another person", async ({ page }) => {
  const phone = uniquePhone();
  await createPatient({ full_name_ar: "نور الدين بابكر", phone, sex: "male" });
  await signIn(page, "ar", "warm");
  await openNewPatient(page, "ar");
  await page.getByLabel(tr("ar", "patients:form.nameAr")).fill("نور الدين بابكر الابن");
  await page.getByRole("radio", { name: tr("ar", "common:sex.male") }).check();
  await page.getByLabel(tr("ar", "patients:form.phone"), { exact: true }).fill(phone);
  await expect(page.getByRole("button", { name: tr("ar", "patients:duplicates.review") })).toBeVisible();
  await page.getByRole("button", { name: tr("ar", "patients:new.submit") }).click();
  await page.getByRole("button", { name: tr("ar", "patients:duplicates.registerAnyway") }).click();
  await expect(page).toHaveURL(/\/patients\/\d+$/);
  await expect(page.locator("#main h1")).toHaveText("نور الدين بابكر الابن");
});

test("@patients registration asks for the sex instead of assuming one", async ({ page }) => {
  await signIn(page, "en", "light");
  await openNewPatient(page, "en");
  for (const sex of ["male", "female"] as const) {
    await expect(page.getByRole("radio", { name: tr("en", `common:sex.${sex}`) })).not.toBeChecked();
  }
  await page.getByLabel(tr("en", "patients:form.nameEn")).fill("Sex Not Chosen");
  await page.getByRole("button", { name: tr("en", "patients:new.submit") }).click();
  await expect(page.getByText(tr("en", "validation.selectOption")).first()).toBeVisible();
  await expect(page).toHaveURL(/\/patients\/new$/);
});

test("@patients emergency registration, then completion", async ({ page }) => {
  await signIn(page, "ar", "light");
  await page.goto("/patients");
  await page.getByRole("button", { name: tr("ar", "patients:emergency.open") }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(tr("ar", "patients:emergency.name")).fill("رجل مجهول طوارئ");
  await dialog.getByRole("button", { name: tr("ar", "patients:emergency.submit") }).click();

  await expect(page).toHaveURL(/\/patients\/\d+$/);
  await expect(page.getByText(tr("ar", "patients:profile.incompleteTitle")).first()).toBeVisible();

  await page.getByRole("button", { name: tr("ar", "patients:edit.completeOpen") }).click();
  const edit = page.getByRole("dialog");
  await edit.getByRole("radio", { name: tr("ar", "common:sex.male") }).check();
  await edit.getByLabel(tr("ar", "patients:form.dateOfBirth")).fill("1979-07-01");
  await edit.getByLabel(tr("ar", "patients:form.phone"), { exact: true }).fill(uniquePhone());
  await edit.getByRole("button", { name: tr("ar", "common:actions.save") }).click();

  await expect(page.getByText(tr("ar", "patients:edit.completed"))).toBeVisible();
  await expect(page.getByText(tr("ar", "patients:profile.incompleteTitle"))).toHaveCount(0);
});
