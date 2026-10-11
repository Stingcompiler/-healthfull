/**
 * Phase 8 follow-up (ADR 0018): an admission made in error is cancelled from the bed board
 * with a reason and a second person's credentials (invariant 4); unbilled nights are voided,
 * and invoiced nights send the nurse to the cashier first (invariant 2).
 * Filter with `make e2e E2E_GREP=@followups`.
 */
import { expect, test, type Page } from "@playwright/test";

import { ANONYMOUS_STATE } from "../../fixtures/state";
import { E2E_PASSWORD } from "../../fixtures/users";
import {
  apiAs,
  approveInvoice,
  closeShift,
  createPatient,
  disposeApiClients,
  expectNoHorizontalScroll,
  fixture,
  FixtureError,
  login,
  setPrefs,
  snap,
  tr,
  trackConsoleErrors,
} from "../../helpers";

test.describe.configure({ mode: "serial", timeout: 180_000 });
test.use({ storageState: ANONYMOUS_STATE });

test.afterAll(async () => {
  await fixture("nursing_discharge_all", {});
  await closeShift().catch((error: unknown) => {
    if (!(error instanceof FixtureError && error.code === "SHIFT_NOT_OPEN")) throw error;
  });
  await disposeApiClients();
});

interface BoardRow {
  wards: { beds: { code: string; status: string }[] }[];
}

interface AdmissionRow {
  status: string;
  cancel_reason: string | null;
  cancelled_by: { id: number } | null;
  cancel_approved_by: { id: number } | null;
}

async function freeBed(): Promise<string> {
  const nurse = await apiAs("nurse");
  const board = await nurse.get<BoardRow>("/api/visits/inpatient/board");
  const free = board.wards.flatMap((w) => w.beds).filter((b) => b.status === "available");
  const bed = free.at(-1);
  if (!bed) throw new Error("the seed needs a free bed");
  return bed.code;
}

/** An admission `days` ago on a free bed, with its passed nights charged. */
async function admitted(fullName: string, days: number) {
  const { patient } = await createPatient({ full_name_en: fullName });
  const adm = await fixture<{ id: number; bed: string; visit_id: number }>("nursing_admission", {
    patient: patient.id,
    bed: await freeBed(),
    days_ago: days,
  });
  await (await apiAs("nurse")).post("/api/visits/inpatient/charge-due", {});
  return adm;
}

async function choose(page: Page, label: string, option: string): Promise<void> {
  await page.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

test.describe("@followups @nursing admission in error", () => {
  test("cancelled with a manager's approval: bed freed, unbilled nights voided", async ({ page }) => {
    const logged = trackConsoleErrors(page, { allowAnonymousMe: true });
    await fixture("nursing_discharge_all", {});
    const adm = await admitted("Hamid Elnour Babiker Musa", 2);

    await page.setViewportSize({ width: 375, height: 812 });
    await login(page, "nurse");
    await setPrefs(page, { theme: "light", lang: "en" });
    await page.goto("/nursing/beds");
    const card = page.locator(`[data-testid="bed-card"][data-bed-code="${adm.bed}"]`);
    await expect(card).toContainText("Hamid");
    await card.getByTestId("bed-cancel-admission").click();
    const dialog = page.getByTestId("cancel-admission-dialog");
    await expect(dialog).toContainText(tr("en", "nursing:cancelAdmission.nightsVoided", { count: "2" }));
    await choose(page, tr("en", "reason.code"), "Wrong patient admitted");
    await dialog.getByLabel(tr("en", "reason.note")).fill("Admitted on the wrong file");

    // The nurse cannot approve her own cancellation.
    await dialog.getByLabel(tr("en", "approver.username")).fill("nurse");
    await dialog.getByLabel(tr("en", "approver.password")).fill(E2E_PASSWORD);
    await dialog.getByTestId("cancel-admission-confirm").click();
    await expect(dialog.getByText(tr("en", "errors:SECOND_APPROVER_REQUIRED"))).toBeVisible();
    await expectNoHorizontalScroll(page);
    await snap(page, "followups-cancel-admission");

    await dialog.getByLabel(tr("en", "approver.username")).fill("manager");
    await dialog.getByLabel(tr("en", "approver.password")).fill(E2E_PASSWORD);
    await dialog.getByTestId("cancel-admission-confirm").click();
    await expect(dialog).toBeHidden();
    await expect(page.locator('[data-testid="bed-card"]', { hasText: "Hamid" })).toHaveCount(0);
    await expect(card).toHaveAttribute("data-status", "available");

    const nurse = await apiAs("nurse");
    const row = await nurse.get<AdmissionRow>(`/api/visits/inpatient/admissions/${String(adm.id)}`);
    expect(row.status).toBe("cancelled");
    expect(row.cancel_reason).toBe("WRONG_PATIENT");
    expect(row.cancelled_by?.id).not.toBe(row.cancel_approved_by?.id);
    // The voided nights left the cashier's list of lines to invoice.
    const cashier = await apiAs("cashier");
    const billingView = await cashier.get<{
      unbilled: { order_source: string }[];
    }>(`/api/billing/visits/${String(adm.visit_id)}`);
    expect(billingView.unbilled.filter((l) => l.order_source === "bed_charge")).toHaveLength(0);
    // The refused self-approval is a documented 409, which Chrome logs as a failed load.
    expect(logged.errors().filter((e) => !e.includes("status of 409"))).toEqual([]);
  });

  test("invoiced nights direct the nurse to the cashier's credit note", async ({ page }) => {
    await fixture("nursing_discharge_all", {});
    const adm = await admitted("Sawsan Ibrahim Eltayeb Hassan", 1);
    await approveInvoice({ visit: adm.visit_id });

    await page.setViewportSize({ width: 768, height: 1024 });
    await login(page, "nurse");
    await setPrefs(page, { theme: "dark", lang: "ar" });
    await page.goto("/nursing/beds");
    const card = page.locator(`[data-testid="bed-card"][data-bed-code="${adm.bed}"]`);
    await expect(card.getByTestId("bed-nights-invoiced")).toBeVisible();
    await card.getByTestId("bed-cancel-admission").click();
    const dialog = page.getByTestId("cancel-admission-dialog");
    await expect(dialog).toContainText(tr("ar", "nursing:cancelAdmission.invoicedTitle", { count: "1" }));
    await expect(dialog.getByTestId("cancel-admission-confirm")).toHaveCount(0);
    await expectNoHorizontalScroll(page);
    await snap(page, "followups-cancel-admission-invoiced");
    // The server says the same to a direct request.
    const nurse = await apiAs("nurse");
    const refused = await nurse.post<{ code: string }>(
      `/api/visits/inpatient/admissions/${String(adm.id)}/cancel`,
      {
        reason_code: "WRONG_PATIENT",
        approver: { username: "manager", password: E2E_PASSWORD },
      },
      { expect: 409 },
    );
    expect(refused.code).toBe("ADMISSION_NIGHTS_INVOICED");
  });
});
