/**
 * Nursing (FLOW step 7, FEATURES 3.4, 10.1-10.3, 10.5): a paid procedure appears on the desk
 * and is done in one tap (with an undo window), an unpaid one never appears (invariant 1);
 * vitals a nurse records are visible to the doctor; a patient is admitted, a bed night is
 * charged for the cashier, and the patient is discharged.
 * Filter with `make e2e E2E_GREP=@nursing`.
 */
import { expect, test, type Page } from "@playwright/test";

import { ANONYMOUS_STATE } from "../../fixtures/state";
import {
  apiAs,
  approveInvoice,
  closeShift,
  createPatient,
  createVisit,
  disposeApiClients,
  expectNoHorizontalScroll,
  fixture,
  FixtureError,
  login,
  orderLines,
  paidVisit,
  pay,
  setPrefs,
  snap,
  tr,
  trackConsoleErrors,
  type PaidVisitResult,
  type ServiceLineRef,
} from "../../helpers";

test.describe.configure({ timeout: 180_000 });
test.use({ storageState: ANONYMOUS_STATE });

test.afterAll(async () => {
  // Leave the shared e2e database as the next spec expects it: no open till, free beds.
  await fixture("nursing_discharge_all", {});
  await closeShift().catch((error: unknown) => {
    if (!(error instanceof FixtureError && error.code === "SHIFT_NOT_OPEN")) throw error;
  });
  await disposeApiClients();
});

/** A line in the doctor's view: status requested, paid, in_progress, done or cancelled. */
interface LineRow {
  id: number;
  status: string;
}

interface BoardRow {
  wards: { beds: { id: number; code: string; status: string; occupant: { admission_id: number } | null }[] }[];
}

/** A paid visit with one paid procedure line of `service`. */
async function paidProcedure(
  service: string,
  fullName: string,
): Promise<{ ready: PaidVisitResult; line: ServiceLineRef }> {
  const ready = await paidVisit({ patient_fields: { full_name_en: fullName } });
  const [line] = await orderLines({ visit: ready.visit, items: [{ service }] });
  if (!line) throw new Error("no line ordered");
  const { invoice } = await approveInvoice({ visit: ready.visit, lines: [line.id] });
  await pay({ invoice });
  return { ready, line };
}

async function lineStatus(visitId: number, lineId: number): Promise<LineRow | undefined> {
  const doctor = await apiAs("doctor");
  const rows = await doctor.get<LineRow[]>(`/api/orders/visits/${String(visitId)}/lines`);
  return rows.find((r) => r.id === lineId);
}

async function openAs(page: Page, who: "nurse" | "doctor", lang: "en" | "ar" = "en"): Promise<void> {
  await login(page, who);
  await setPrefs(page, { theme: "light", lang });
}

test.describe("@nursing procedure desk", () => {
  test.use({ viewport: { width: 768, height: 1024 } });

  test("a paid procedure is done in one tap; an unpaid one never shows; undo keeps it waiting", async ({
    page,
  }) => {
    const logged = trackConsoleErrors(page, { allowAnonymousMe: true });
    const paid = await paidProcedure("PRC-INJ", "Hawa Ibrahim Adam Yousif");
    const undone = await paidProcedure("PRC-NEB", "Omer Salih Hamid Taha");
    const { patient: unpaidPatient } = await createPatient({ full_name_en: "Nasir Elamin Bashir Ali" });
    const unpaidVisit = await createVisit({ patient: unpaidPatient });
    const [unpaid] = await orderLines({ visit: unpaidVisit.visit, items: [{ service: "PRC-DRESS" }] });
    if (!unpaid) throw new Error("no unpaid line");

    await openAs(page, "nurse");
    await page.goto("/nursing");
    const card = page.locator(`[data-testid="procedure-card"][data-line-id="${String(paid.line.id)}"]`);
    await expect(card).toBeVisible();
    await expect(card).toContainText(paid.ready.patient.file_no);
    // Invariant 1: the unpaid dressing is not on the desk.
    await expect(page.locator(`[data-testid="procedure-card"][data-line-id="${String(unpaid.id)}"]`)).toHaveCount(0);
    await expectNoHorizontalScroll(page);
    await snap(page, "nursing-desk-flow");

    // Undo within the window: nothing is sent, the line stays waiting.
    const undoCard = page.locator(`[data-testid="procedure-card"][data-line-id="${String(undone.line.id)}"]`);
    await undoCard.getByTestId("procedure-done").click();
    await expect(undoCard.getByTestId("procedure-undo")).toBeVisible();
    await undoCard.getByTestId("procedure-undo").click();
    await expect(undoCard.getByTestId("procedure-done")).toBeVisible();

    // One tap: the undo window shows, then the mark is sent with who and when.
    await card.getByTestId("procedure-done").click();
    await expect(card.getByTestId("procedure-undo")).toBeVisible();
    await snap(page, "nursing-desk-undo-window");
    await expect(card).toHaveCount(0, { timeout: 15_000 });
    await expect(page.getByTestId("procedures-done").locator(`[data-line-id="${String(paid.line.id)}"]`)).toBeVisible();
    expect((await lineStatus(paid.ready.visit.id, paid.line.id))?.status).toBe("done");

    // The undone line was never sent.
    expect((await lineStatus(undone.ready.visit.id, undone.line.id))?.status).toBe("paid");
    await expect(undoCard.getByTestId("procedure-done")).toBeVisible();
    expect(logged.errors()).toEqual([]);
  });

  test("done with a note in Arabic on a phone", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    const paid = await paidProcedure("PRC-CANNULA", "Mariam Hassan Elfadil Musa");
    await openAs(page, "nurse", "ar");
    await page.goto("/nursing");
    const card = page.locator(`[data-testid="procedure-card"][data-line-id="${String(paid.line.id)}"]`);
    await expect(card).toBeVisible();
    await card.getByRole("button", { name: new RegExp(tr("ar", "nursing:procedures.withNote")) }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel(tr("ar", "nursing:procedures.noteDialog.label")).fill("الذراع اليسرى");
    await dialog.getByTestId("procedure-note-confirm").click();
    await expect(card.getByTestId("procedure-undo")).toBeVisible();
    await card.getByRole("button", { name: tr("ar", "nursing:procedures.saveNow") }).click();
    await expect(card).toHaveCount(0, { timeout: 15_000 });
    const done = page.getByTestId("procedures-done").locator(`[data-line-id="${String(paid.line.id)}"]`);
    await expect(done).toContainText("الذراع اليسرى");
    await expectNoHorizontalScroll(page);
    await snap(page, "nursing-desk-done");
  });
});

test.describe("@nursing vitals", () => {
  test("vitals saved by a nurse are visible to the doctor", async ({ page }) => {
    const logged = trackConsoleErrors(page, { allowAnonymousMe: true });
    const ready = await paidVisit({ patient_fields: { full_name_en: "Sumaya Abdelgadir Nour Eldin" } });
    const fileNo = ready.patient.file_no;

    await openAs(page, "nurse");
    await page.goto("/nursing/visits");
    await page.getByLabel(tr("en", "nursing:visits.search")).fill(fileNo);
    const row = page.locator(`[data-testid="nursing-visit"][data-file-no="${fileNo}"]`);
    await expect(row).toBeVisible();
    await expect(row).toContainText(tr("en", "nursing:visits.noVitals"));
    await row.getByRole("link", { name: new RegExp(tr("en", "nursing:visits.open")) }).click();
    await expect(page).toHaveURL(new RegExp(`/nursing/visits/${String(ready.visit.id)}$`));

    const form = page.getByTestId("vitals-form");
    await form.getByLabel(tr("en", "nursing:vitals.field.temperature_c")).fill("38.7");
    await form.getByLabel(tr("en", "nursing:vitals.field.bp_systolic")).fill("124");
    await form.getByLabel(tr("en", "nursing:vitals.field.bp_diastolic")).fill("82");
    await form.getByLabel(tr("en", "nursing:vitals.field.pulse_bpm")).fill("104");
    await page.getByTestId("vitals-save").click();
    await expect(page.getByText(tr("en", "nursing:vitals.savedToast"))).toBeVisible();
    await expect(page.getByTestId("vitals-list")).toContainText("38.7");

    await page.getByLabel(tr("en", "nursing:notes.label")).fill("Febrile on arrival, oral fluids given.");
    await page.getByTestId("nursing-note-add").click();
    await expect(page.getByTestId("nursing-notes")).toContainText("Febrile on arrival");
    await expectNoHorizontalScroll(page);
    await snap(page, "nursing-chart-flow");
    expect(logged.errors()).toEqual([]);

    // The doctor sees the same vitals in the visit workspace.
    await page.context().clearCookies();
    await openAs(page, "doctor");
    await page.goto(`/clinic/visits/${String(ready.visit.id)}`);
    const vitals = page.locator("section", { has: page.locator("#vitals-heading") });
    await expect(vitals).toContainText("38.7");
    await expect(vitals).toContainText("124/82");
  });
});

test.describe("@nursing inpatient", () => {
  test("admit a patient, post a bed night for the cashier, discharge", async ({ page }) => {
    const logged = trackConsoleErrors(page, { allowAnonymousMe: true });
    await fixture("nursing_discharge_all", {});
    const { patient } = await createPatient({ full_name_en: "Abdelmoneim Yassin Elhaj Omer" });
    const { patient: older } = await createPatient({ full_name_en: "Zeinab Mahgoub Ahmed Saad" });

    // Someone admitted yesterday: one night is due.
    const nurse = await apiAs("nurse");
    const board = await nurse.get<BoardRow>("/api/visits/inpatient/board");
    const free = board.wards.flatMap((w) => w.beds).filter((b) => b.status === "available");
    const lastFree = free.at(-1);
    if (!lastFree || free.length < 2) throw new Error("the seed needs two free beds");
    const earlier = await fixture<{ id: number; bed: string }>("nursing_admission", {
      patient: older.id,
      bed: lastFree.code,
      days_ago: 1,
    });

    await openAs(page, "nurse");
    await page.goto("/nursing/beds");
    await expect(page.locator(`[data-testid="bed-card"][data-bed-code="${earlier.bed}"]`)).toContainText(
      "Zeinab",
    );

    // Admit from the board.
    await page.getByTestId("admit-open").click();
    const dialog = page.getByRole("dialog");
    await dialog.getByTestId("admit-patient-search").fill(patient.file_no);
    await dialog.locator(`[data-testid="admit-patient-option"][data-file-no="${patient.file_no}"]`).click();
    await expect(dialog.getByTestId("admit-patient")).toContainText("Abdelmoneim");
    await dialog.getByTestId("admit-doctor").click();
    await page.getByRole("option", { name: "Dr. Ahmed Altayeb" }).click();
    await dialog.getByTestId("admit-bed").click();
    await page.getByRole("option").first().click();
    await dialog.getByLabel(tr("en", "nursing:admit.diagnosis")).fill("Severe malaria");
    await dialog.getByTestId("admit-confirm").click();
    await expect(dialog).toBeHidden();
    const admitted = page.locator('[data-testid="bed-card"]', { hasText: "Abdelmoneim" });
    await expect(admitted).toHaveAttribute("data-status", "occupied");
    await expect(admitted).toContainText("Severe malaria");
    await expectNoHorizontalScroll(page);
    await snap(page, "nursing-beds-flow");

    // The daily run: the passed night becomes a line on the visit for the cashier.
    await page.getByTestId("post-nights").click();
    await expect(page.getByText(tr("en", "nursing:beds.postedToast", { count: "1" }))).toBeVisible();
    const earlierCard = page.locator(`[data-testid="bed-card"][data-bed-code="${earlier.bed}"]`);
    await expect(earlierCard.getByTestId("bed-nights-charged")).toContainText(
      tr("en", "nursing:beds.nightsCharged", { count: "1" }),
    );
    const adm = await nurse.get<{ visit_id: number; nights_charged: number }>(
      `/api/visits/inpatient/admissions/${String(earlier.id)}`,
    );
    expect(adm.nights_charged).toBe(1);
    const cashier = await apiAs("cashier");
    const detail = await cashier.get<{ lines: { order_source: string; state: string }[] }>(
      `/api/visits/${String(adm.visit_id)}`,
    );
    expect(detail.lines.filter((l) => l.order_source === "bed_charge")).toHaveLength(1);

    // Discharge the patient admitted today: one night is charged, the bed is free again.
    await admitted.getByTestId("bed-discharge").click();
    const discharge = page.getByRole("dialog");
    await expect(discharge).toContainText(tr("en", "nursing:discharge.nights", { count: "1" }));
    await discharge.getByLabel(tr("en", "nursing:discharge.summary")).fill("Improved, oral treatment at home");
    await discharge.getByTestId("discharge-confirm").click();
    await expect(discharge).toBeHidden();
    await expect(page.locator('[data-testid="bed-card"]', { hasText: "Abdelmoneim" })).toHaveCount(0);
    expect(logged.errors()).toEqual([]);
  });
});
