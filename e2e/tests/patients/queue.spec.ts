/**
 * Visits and the queue (FEATURES 2.1-2.3, 2.6): open a visit from the patient file with its
 * token slip, then the reception board calls the paid token, the waiting-room screen shows it
 * with an abbreviated name, and the consultation is started and finished.
 */
import { expect, test, type Page } from "@playwright/test";

import {
  apiAs,
  createPatient,
  disposeApiClients,
  expectNoHorizontalScroll,
  login,
  paidVisit,
  setPrefs,
  tr,
  type Lang,
} from "../../helpers";

test.describe.configure({ timeout: 120_000 });
test.afterAll(disposeApiClients);

async function signIn(page: Page, lang: Lang, theme: "light" | "dark" | "warm"): Promise<void> {
  await login(page, "reception");
  await setPrefs(page, { theme, lang });
}

interface Named {
  id: number;
  code: string;
  name_ar: string;
  name_en: string;
}

async function department(code: string): Promise<Named> {
  const reception = await apiAs("reception");
  const options = await reception.get<{ departments: Named[] }>("/api/visits/options");
  const found = options.departments.find((d) => d.code === code);
  if (!found) throw new Error(`No department ${code}`);
  return found;
}

async function chooseOption(page: Page, label: string, option: string): Promise<void> {
  await page.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

const VIEWPORTS: { lang: Lang; width: number; height: number }[] = [
  { lang: "en", width: 1280, height: 800 },
  { lang: "ar", width: 375, height: 812 },
];

for (const v of VIEWPORTS) {
  test(`@patients open a visit from the file and print the token (${v.lang}, ${String(v.width)}px)`, async ({
    page,
  }) => {
    const { patient } = await createPatient({ full_name_ar: "مريم عثمان علي", full_name_en: "Mariam Osman Ali" });
    const gen = await department("GEN");
    await page.setViewportSize({ width: v.width, height: v.height });
    await signIn(page, v.lang, "light");
    await page.goto(`/patients/${String(patient.id)}`);

    await page.getByRole("button", { name: tr(v.lang, "patients:profile.newVisit") }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByTestId("picked-patient")).toContainText(patient.file_no);
    await chooseOption(page, tr(v.lang, "visits:create.department"), v.lang === "ar" ? gen.name_ar : gen.name_en);
    await chooseOption(
      page,
      tr(v.lang, "visits:create.doctor"),
      v.lang === "ar" ? "د. أحمد الطيب" : "Dr. Ahmed Altayeb",
    );
    await dialog.getByRole("button", { name: tr(v.lang, "visits:create.submit") }).click();

    const slip = page.getByRole("dialog");
    await expect(slip.getByRole("heading", { name: tr(v.lang, "visits:token.title") })).toBeVisible();
    await expect(slip.getByTestId("token-number")).toHaveText(/\S/);
    await expect(slip.getByTestId("token-slip")).toContainText(patient.file_no);
    await expectNoHorizontalScroll(page);
    await page.keyboard.press("Escape");
    await expect(slip).toHaveCount(0);

    // The visit is on the file with its timeline.
    const visit = page.getByTestId("visit-item").first();
    await expect(visit).toContainText(tr(v.lang, "visits:visitStatus.open"));
    await visit.getByRole("button", { name: tr(v.lang, "visits:timeline.title") }).click();
    await expect(visit).toContainText(tr(v.lang, "visits:timeline.kind.visit_created"));
    await expect(visit).toContainText(tr(v.lang, "visits:timeline.kind.line_ordered"));
  });
}

test("@patients board calls the paid token and the waiting room shows it", async ({ page }) => {
  const ready = await paidVisit({
    doctor: "doctor",
    patient_fields: { full_name_ar: "عبد الله الطيب محمد", full_name_en: "Abdalla Altayeb Mohamed" },
  });
  const gen = await department("GEN");
  const token = ready.queue_entry?.token_no;
  expect(token).toBeDefined();

  await signIn(page, "en", "dark");
  await page.goto("/queue");
  await chooseOption(page, tr("en", "visits:board.department"), gen.name_en);
  await expect(page.getByText(ready.patient.file_no).first()).toBeVisible();

  // Call until our token is called (earlier paid tokens from other specs may be waiting).
  let calledOurs = false;
  for (let i = 0; i < 30 && !calledOurs; i += 1) {
    const answer = page.waitForResponse((r) => r.url().includes("/api/visits/queue/call-next"));
    await page.getByRole("button", { name: tr("en", "visits:board.callNext") }).click();
    const response = await answer;
    expect(response.status(), "the queue emptied before our token was called").toBe(200);
    calledOurs = ((await response.json()) as { visit_id: number }).visit_id === ready.visit.id;
  }
  expect(calledOurs).toBe(true);
  await expect(page.getByRole("row").filter({ hasText: ready.patient.file_no })).toContainText(
    tr("en", "visits:queueStatus.called"),
  );

  await page.goto(`/queue/display?department=${String(gen.id)}`);
  const current = page.getByTestId("display-current");
  await expect(current).toContainText(String(token));
  await expect(current).toContainText("Abdalla A.");
  await expect(current).not.toContainText("Altayeb Mohamed");
  await expectNoHorizontalScroll(page);

  await setPrefs(page, { theme: "dark", lang: "ar" });
  await page.reload();
  await expect(page.getByTestId("display-current")).toContainText("عبد الله ط.");

  // Start and finish the consultation from the board.
  await page.goto("/queue");
  const row = page.getByRole("row").filter({ hasText: ready.patient.file_no });
  await row.getByRole("button", { name: tr("ar", "common:table.rowActions") }).click();
  await page.getByRole("menuitem", { name: tr("ar", "visits:board.action.start") }).click();
  await expect(row).toContainText(tr("ar", "visits:queueStatus.in_progress"));
  await row.getByRole("button", { name: tr("ar", "common:table.rowActions") }).click();
  await page.getByRole("menuitem", { name: tr("ar", "visits:board.action.finish") }).click();
  await expect(row).toHaveCount(0);
});
