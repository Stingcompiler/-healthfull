/**
 * The doctor's cycle (FLOW step 3, FEATURES 2.3, 3.1-3.8): call the next paid patient, write
 * the note with an ICD-10 diagnosis, order three lab tests and a prescription, get the allergy
 * alert and override it with a reason, and follow the order statuses as the cashier works.
 * Filter with `make e2e E2E_GREP=@clinic`.
 */
import { expect, test, type Page } from "@playwright/test";

import { ANONYMOUS_STATE } from "../../fixtures/state";
import {
  apiAs,
  approveInvoice,
  closeShift,
  createPatient,
  disposeApiClients,
  expectNoHorizontalScroll,
  FixtureError,
  login,
  paidVisit,
  pay,
  setPrefs,
  tr,
  trackConsoleErrors,
} from "../../helpers";

const DOCTOR = "gynecologist" as const;

test.describe.configure({ timeout: 180_000 });
test.use({ storageState: ANONYMOUS_STATE });

test.afterAll(async () => {
  await closeShift().catch((error: unknown) => {
    if (!(error instanceof FixtureError && error.code === "SHIFT_NOT_OPEN")) throw error;
  });
  await disposeApiClients();
});

interface WorklistRow {
  id: number;
  status: string;
  patient: { file_no: string };
  visit: { id: number };
}

/** Finish whatever earlier specs left in this doctor's queue, so "call next" calls ours. */
async function drainQueue(keepFileNo?: string): Promise<void> {
  const doctor = await apiAs(DOCTOR);
  const rows = await doctor.get<WorklistRow[]>("/api/clinical/worklist");
  for (const row of rows) {
    if (row.patient.file_no === keepFileNo) continue;
    const steps = { waiting: ["call", "start", "complete"], called: ["start", "complete"], in_progress: ["complete"] };
    for (const action of steps[row.status as keyof typeof steps] ?? []) {
      await doctor.post(`/api/clinical/worklist/${String(row.id)}/action`, { action });
    }
  }
}

async function openAsDoctor(page: Page): Promise<void> {
  await login(page, DOCTOR);
  await setPrefs(page, { theme: "light", lang: "en" });
}

test.describe("@clinic doctor workspace", () => {
  test("calls the patient, writes the note, orders tests and a prescription with an allergy override", async ({
    page,
  }) => {
    const logged = trackConsoleErrors(page, { allowAnonymousMe: true });
    const { patient } = await createPatient({
      sex: "female",
      full_name_en: "Fatima Abdelrahman Osman",
      allergies: ["PENICILLIN"],
    });
    await drainQueue();
    const ready = await paidVisit({ doctor: DOCTOR, patient: patient.id });
    const visitId = ready.visit.id;

    await openAsDoctor(page);
    await page.goto("/clinic");
    const entry = page.locator(`[data-testid="queue-entry"][data-file-no="${patient.file_no}"]`);
    await expect(entry).toBeVisible();
    // The allergy is prominent before the doctor even opens the file.
    await expect(entry.getByRole("group", { name: tr("en", "patient.allergyAlert") })).toContainText(/penicillin/i);

    // Call next: our patient is the only one waiting.
    await page.getByTestId("call-next").click();
    await expect(page).toHaveURL(new RegExp(`/clinic/visits/${String(visitId)}$`));
    await expect(page.getByTestId("summary-panel")).toContainText(/penicillin/i);
    await page.getByTestId("queue-start").click();
    await expect(page.getByTestId("queue-complete")).toBeVisible();

    // Clinical note with an ICD-10 diagnosis.
    const note = page.getByTestId("note-form");
    await note.getByLabel(tr("en", "clinic:note.complaint")).fill("Fever and headache for three days");
    await note.getByLabel(tr("en", "clinic:note.examination")).fill("T 38.6, no neck stiffness");
    await note.getByLabel(tr("en", "clinic:note.plan")).fill("Malaria film, CBC, glucose; antibiotics");
    await page.getByTestId("note-save").click();
    await expect(page.getByText(tr("en", "clinic:note.savedToast"))).toBeVisible();

    await page.getByTestId("icd10-search").fill("malaria");
    const results = page.getByTestId("icd10-results");
    await expect(results).toBeVisible();
    await results.getByRole("button", { name: /B54/ }).click();
    await page.getByTestId("diagnosis-add").click();
    await expect(page.getByTestId("diagnosis-list")).toContainText("B54");

    await page.getByTestId("note-sign").click();
    await page.getByRole("alertdialog").getByRole("button", { name: tr("en", "clinic:note.sign") }).click();
    await expect(page.getByTestId("signed-note")).toContainText("Fever and headache");

    // Orders: three lab tests and a prescription from the catalog.
    await page.getByTestId("tab-orders").click();
    const search = page.getByTestId("catalog-search");
    for (const code of ["LAB-CBC", "LAB-BFMP", "LAB-FBS"]) {
      await search.fill(code);
      await expect(page.getByTestId("catalog-results").locator(`[data-service-code="${code}"]`)).toBeVisible();
      await search.press("Enter");
      await expect(page.locator(`[data-testid="draft-item"][data-service-code="${code}"]`)).toBeVisible();
    }
    await search.fill("amoxicillin");
    await page.getByTestId("catalog-results").locator('[data-service-code="DRG-AMOX500"]').click();
    const rx = page.locator('[data-testid="draft-item"][data-service-code="DRG-AMOX500"]');
    await rx.getByTestId("rx-frequency").click();
    await page.getByTestId("rx-frequency-TID").click();
    await rx.getByTestId("rx-days").fill("7");
    // The quantity is computed by the server: 1 capsule x 3 a day x 7 days.
    await expect(rx.getByTestId("rx-quantity")).toContainText("21");

    // Placing the order raises the allergy alert; it needs a reason.
    await page.getByTestId("place-orders").click();
    const dialog = page.getByTestId("allergy-override-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByTestId("allergy-alerts")).toContainText(/penicillin/i);
    const confirm = dialog.getByTestId("override-confirm");
    await expect(confirm).toBeDisabled();
    await dialog.getByTestId("override-reason").fill("  ");
    await expect(confirm).toBeDisabled();
    await dialog.getByTestId("override-reason").fill("Mild rash years ago; no alternative available");
    await expect(confirm).toBeEnabled();
    await confirm.click();
    await expect(dialog).toBeHidden();

    const lines = page.getByTestId("order-line");
    await expect(lines).toHaveCount(4);
    await expect(page.locator('[data-testid="order-line"][data-status="requested"]')).toHaveCount(4);
    const amoxLine = page.locator('[data-testid="order-line"][data-service-code="DRG-AMOX500"]');
    await expect(amoxLine).toContainText("Mild rash years ago");
    await expect(amoxLine).toContainText(tr("en", "status.requested"));
    // Doctors never see prices.
    await expect(page.getByTestId("order-lines")).not.toContainText(/SDG|ج\.س/);

    // The cashier bills and collects: the doctor sees the lines become paid.
    const { invoice } = await approveInvoice({ visit: visitId });
    await pay({ invoice });
    await page.reload();
    await page.getByTestId("tab-orders").click();
    await expect(page.locator('[data-testid="order-line"][data-status="paid"]')).toHaveCount(4);
    await expect(amoxLine).toContainText(tr("en", "status.paid"));
    await expectNoHorizontalScroll(page);

    // Finish the consultation; the visit stays open for results.
    await page.getByTestId("queue-complete").click();
    await page.getByRole("alertdialog").getByRole("button", { name: tr("en", "clinic:queue.complete") }).click();
    await expect(page.getByTestId("queue-complete")).toBeHidden();
    await page.goto("/clinic");
    await expect(entry).toContainText(tr("en", "clinic:queueStatus.done"));

    // The allergy alert is a 409 answer by design; nothing else may fail.
    expect(logged.errors().filter((e) => !/status of 409/.test(e)), "console errors").toEqual([]);
  });

  test("the doctor's workspace stacks on a phone without horizontal scroll", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    const ready = await paidVisit({ doctor: DOCTOR, patient_fields: { allergies: ["NSAID"] } });
    await openAsDoctor(page);
    await page.goto(`/clinic/visits/${String(ready.visit.id)}`);
    await expect(page.getByTestId("summary-panel")).toBeVisible();
    await expect(page.getByTestId("note-form")).toBeVisible();
    await expectNoHorizontalScroll(page);
    await page.getByTestId("tab-orders").click();
    await expect(page.getByTestId("catalog-picker")).toBeVisible();
    await expectNoHorizontalScroll(page);
    await drainQueue();
  });
});
