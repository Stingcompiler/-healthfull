/**
 * Printed prescription and referral letter (FEATURES 3.5, 3.9; inspection F03): the doctor
 * opens them from the visit, the paper switches between Arabic and English, carries the
 * center's identity and the print template, and never a price.
 * Filter with `make e2e E2E_GREP=@prints`.
 */
import { expect, test } from "@playwright/test";

import { ANONYMOUS_STATE } from "../../fixtures/state";
import {
  apiAs,
  disposeApiClients,
  expectNoHorizontalScroll,
  login,
  orderLines,
  paidVisit,
  setPrefs,
  snap,
  tr,
  trackConsoleErrors,
} from "../../helpers";

test.describe.configure({ timeout: 150_000 });
test.use({ storageState: ANONYMOUS_STATE });
test.afterAll(disposeApiClients);

/** Money as any screen would print it: a price must never reach a clinic document. */
const MONEY = /\d[\d,]*\.\d{2}|SDG|ج\.س/;

test.describe("@clinic @prints clinic documents", () => {
  test("the doctor prints the prescription and the referral letter in Arabic and English", async ({ page }) => {
    const logged = trackConsoleErrors(page, { allowAnonymousMe: true });
    const admin = await apiAs("admin");
    await admin.put("/api/core/print-templates/prescription/a4", {
      show_logo: true,
      header_ar: "عيادات الأسرة",
      header_en: "Family clinics",
      footer_ar: "تصرف خلال ٧ أيام",
      footer_en: "Valid for 7 days",
      active: true,
    });
    const { visit } = await paidVisit({
      doctor: "pediatrician",
      patient_fields: { full_name_en: "Hawa Abdelrahim Musa Adam", allergies: ["PENICILLIN"] },
    });
    await orderLines({
      visit,
      items: [
        {
          service: "DRG-PARA500",
          prescription: {
            dose: "1 tablet",
            dose_quantity: "1",
            frequency_code: "TID",
            duration_days: 5,
            instructions: "After meals",
          },
        },
      ],
      as: "pediatrician",
    });
    const doctor = await apiAs("pediatrician");
    await doctor.post(`/api/clinical/visits/${String(visit.id)}/referrals`, {
      kind: "external",
      external_facility: "Khartoum Teaching Hospital",
      reason: "Surgical opinion",
      clinical_summary: "Right lower quadrant pain",
      urgency: "urgent",
    });

    await login(page, "pediatrician");
    await setPrefs(page, { theme: "light", lang: "ar" });
    await page.goto(`/clinic/visits/${String(visit.id)}`);
    await page.getByTestId("tab-orders").click();
    await page.getByTestId("prescription-print-link").click();
    const paper = page.getByTestId("prescription-print");
    await expect(paper).toBeVisible();
    // Arabic paper by default on an Arabic screen.
    await expect(paper).toHaveAttribute("dir", "rtl");
    await expect(paper).toContainText(tr("ar", "clinic:print.prescriptionHeading"));
    await expect(paper).toContainText("عيادات الأسرة");
    await expect(paper).toContainText("تصرف خلال ٧ أيام");
    await expect(paper.getByTestId("print-rx-item")).toHaveCount(1);
    await expect(paper.getByTestId("print-allergies")).not.toHaveText(tr("ar", "clinic:print.noAllergies"));
    expect(await paper.innerText()).not.toMatch(MONEY);
    for (const width of [375, 768, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      await expectNoHorizontalScroll(page);
    }
    await snap(page, "clinic-prescription-print");

    await page.getByTestId("print-lang-en").click();
    await expect(paper).toHaveAttribute("dir", "ltr");
    await expect(paper).toContainText("Prescription");
    await expect(paper).toContainText("Family clinics");
    await expect(paper).toContainText("After meals");
    await expect(paper).toContainText(tr("en", "clinic:frequency.TID"));
    expect(await paper.innerText()).not.toMatch(MONEY);

    // The referral letter, from the visit's referrals.
    await page.goto(`/clinic/visits/${String(visit.id)}`);
    await page.getByTestId("referral-print").first().click();
    const letter = page.getByTestId("referral-print");
    await expect(letter).toBeVisible();
    await expect(letter).toContainText("Khartoum Teaching Hospital");
    await expect(letter).toContainText(tr("ar", "clinic:print.referralHeading"));
    await expect(letter).toContainText(tr("ar", "clinic:referral.urgency.urgent"));
    expect(await letter.innerText()).not.toMatch(MONEY);
    await page.getByTestId("print-lang-en").click();
    await expect(letter).toContainText("Referral letter");
    await expect(letter).toContainText("Surgical opinion");
    for (const width of [375, 768, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      await expectNoHorizontalScroll(page);
    }
    await snap(page, "clinic-referral-print");
    // The print stylesheet keeps only the paper.
    await page.emulateMedia({ media: "print" });
    await expect(page.getByTestId("print")).toBeHidden();
    await expect(letter).toBeVisible();
    expect(logged.errors()).toEqual([]);
  });
});
