/**
 * The lab bench (FEATURES 9.2-9.7, FLOW step 5): only paid tests reach the work list
 * (invariant 1); the technician receives the sample, prints its label and enters results with
 * live flags; the supervisor approves and the doctor then sees the result in the Results tab;
 * an amendment keeps the original; a test that cannot be performed is cancelled with a billing
 * approver and its refund request opens at the cashier.
 */
import { expect, test } from "@playwright/test";

import { E2E_PASSWORD } from "../../fixtures/users";
import { apiAs, disposeApiClients } from "../../helpers";
import { choose, firstLine, labOrder, labProgress, openTest, pageAs, t } from "./kit";

test.describe("@lab bench", () => {
  test.describe.configure({ timeout: 150_000 });
  test.afterAll(disposeApiClients);

  test("a paid test is on the work list, an unpaid one is not", async ({ browser }) => {
    const paid = await labOrder({ tests: ["LAB-FBS"] });
    const unpaid = await labOrder({ tests: ["LAB-FBS"], pay: false });
    expect(unpaid.lab_lines[0]?.billing_status).toBe("invoiced");

    const tech = await pageAs(browser, "labtech");
    await tech.goto(`/lab?q=${encodeURIComponent(paid.patient.file_no)}`);
    const row = tech.locator('[data-slot="data-table"] tbody tr').filter({ hasText: paid.patient.file_no });
    await expect(row).toBeVisible();
    await expect(row.locator('[data-slot="lab-stage"]')).toHaveAttribute("data-stage", "to_collect");

    await tech.goto(`/lab?q=${encodeURIComponent(unpaid.patient.file_no)}`);
    await expect(tech.getByText(t("lab:worklist.empty"))).toBeVisible();
    // Not by the API either (invariant 1).
    const api = await apiAs("labtech");
    const list = await api.get<{ items: { line_id: number }[] }>(
      `/api/lab/worklist?q=${encodeURIComponent(unpaid.patient.file_no)}`,
    );
    expect(list.items).toEqual([]);
  });

  test("results with a critical flag, supervisor approval, the doctor sees them", async ({ browser }) => {
    const order = await labOrder({ tests: ["LAB-CBC"] });
    const lineId = firstLine(order);

    const tech = await pageAs(browser, "labtech");
    await openTest(tech, lineId);
    await tech.getByTestId("receive-sample").click();
    await tech.getByTestId("confirm-receive").click();
    await expect(tech.getByTestId("accession-no")).toBeVisible();
    const accession = (await tech.getByTestId("accession-no").textContent()) ?? "";
    expect(accession).toMatch(/LAB/);

    // The label prints from its own page and the print is recorded.
    await tech.getByTestId("print-label").click();
    await expect(tech.getByTestId("label-accession")).toHaveText(accession);
    await tech.getByTestId("print").click();
    await expect(tech.getByTestId("label-printed")).toBeVisible();
    await tech.goBack();

    // Live flags while typing; the server stores its own.
    const entry = tech.getByTestId("result-entry");
    await expect(entry).toBeVisible();
    await entry.getByTestId("value-WBC").fill("7.4");
    await entry.getByTestId("value-HGB").fill("5.2");
    const hgb = entry.locator('[data-testid="result-param"][data-code="HGB"]');
    await expect(hgb.locator('[data-slot="lab-flag"]')).toHaveText(t("lab:flag.critical_low"));
    await entry.getByTestId("value-PLT").fill("abc");
    await entry.getByTestId("save-results").click();
    await expect(entry.getByText(t("lab:entry.notANumber"))).toBeVisible();
    await entry.getByTestId("value-PLT").fill("250");
    await entry.getByTestId("save-results").click();
    await expect(tech.locator('[data-slot="lab-stage"]').first()).toHaveAttribute("data-stage", "to_approve");
    // A technician never approves.
    await expect(tech.getByTestId("approval-panel")).toHaveCount(0);

    // The supervisor finds it in the approval queue, marked critical, and approves it.
    const sup = await pageAs(browser, "labsup");
    await sup.goto("/lab/approve");
    const queued = sup.locator('[data-slot="data-table"] tbody tr').filter({ hasText: order.patient.file_no });
    await expect(queued.getByTestId("approval-critical")).toBeVisible();
    await queued.getByRole("button").first().click();
    await expect(sup.getByTestId("approval-panel")).toBeVisible();
    await sup.getByTestId("approve-result").click();
    await sup
      .getByRole("button", { name: t("lab:approve.submit") })
      .last()
      .click();
    await expect(sup.locator('[data-slot="lab-stage"]').first()).toHaveAttribute("data-stage", "done");
    await expect(sup.getByTestId("current-result")).toBeVisible();

    // The doctor sees the approved result, with its flag, in the visit's Results tab.
    const doctor = await pageAs(browser, "doctor");
    await doctor.goto(`/clinic/visits/${String(order.visit.id)}`);
    await doctor.getByTestId("tab-results").click();
    const card = doctor.getByTestId("result-card").first();
    await expect(card).toBeVisible();
    await expect(card).toContainText("5.2");
  });

  test("an amendment keeps the original version", async ({ browser }) => {
    const order = await labOrder({ tests: ["LAB-RBS"] });
    const lineId = firstLine(order);
    await labProgress({
      line: lineId,
      stage: "approved",
      values: { GLU: "120" },
    });

    const sup = await pageAs(browser, "labsup");
    await openTest(sup, lineId);
    await sup.getByTestId("amend-result").click();
    await choose(sup, t("reason.code"), "Entry error");
    await sup.getByLabel(t("reason.note")).fill("Glucose typed wrong");
    await sup.getByRole("button", { name: t("lab:amend.confirm") }).click();
    const entry = sup.getByTestId("result-entry");
    await expect(entry).toBeVisible();
    await entry.getByTestId("value-GLU").fill("102");
    await entry.getByTestId("save-results").click();
    await expect(sup.getByTestId("approve-result")).toBeEnabled();
    await sup.getByTestId("approve-result").click();
    await sup
      .getByRole("button", { name: t("lab:approve.submit") })
      .last()
      .click();

    const history = sup.getByTestId("version-history");
    const v1 = history.locator('[data-testid="result-version"][data-version="1"]');
    const v2 = history.locator('[data-testid="result-version"][data-version="2"]');
    await expect(v1).toHaveAttribute("data-status", "amended");
    await expect(v2).toHaveAttribute("data-status", "approved");
    await expect(v1).toContainText("120");
    await expect(v2).toContainText("102");
    await expect(v2.getByTestId("amendment-reason")).toContainText("Glucose typed wrong");

    // The original still prints, marked as replaced.
    await v1.getByTestId("print-version").click();
    await expect(sup.getByTestId("print-superseded")).toBeVisible();
    await expect(sup.getByTestId("result-print")).toContainText("120");
    // The report prints in Arabic too.
    await sup.getByTestId("print-lang-ar").click();
    await expect(sup.getByTestId("result-print")).toHaveAttribute("data-lang", "ar");
  });

  test("a test that cannot be performed opens the refund path", async ({ browser }) => {
    const order = await labOrder({ tests: ["LAB-RFT"] });
    const lineId = firstLine(order);

    const sup = await pageAs(browser, "labsup");
    await openTest(sup, lineId);
    await sup.getByTestId("cannot-perform").click();
    const dialog = sup.getByTestId("cancel-test-dialog");
    await choose(sup, t("reason.code"), "Equipment out of service");
    // A billed test needs the billing approver.
    await dialog.getByTestId("confirm-cancel").click();
    await expect(dialog.getByText(t("validation.required")).first()).toBeVisible();
    await dialog.getByLabel(t("lab:cancel.username")).fill("cashsup");
    await dialog.getByLabel(t("lab:cancel.password")).fill("wrong-password");
    await dialog.getByTestId("confirm-cancel").click();
    await expect(dialog.getByText(t("errors:APPROVER_INVALID"))).toBeVisible();
    await dialog.getByLabel(t("lab:cancel.password")).fill(E2E_PASSWORD);
    await dialog.getByTestId("confirm-cancel").click();
    await expect(sup.getByTestId("cancelled-notice")).toContainText(t("lab:result.refundOpened"));
    await expect(sup.locator('[data-slot="lab-stage"]').first()).toHaveAttribute("data-stage", "cancelled");

    // The patient's money is waiting as a refund request at the cashier.
    const cashsup = await apiAs("cashsup");
    const refunds = await cashsup.get<{
      items: { patient: { id: number }; status: string; amount: string }[];
    }>("/api/payments/refunds?status=requested&page_size=100");
    const mine = refunds.items.filter((r) => r.patient.id === order.patient.id);
    expect(mine).toHaveLength(1);
    expect(mine[0]?.amount).toBe("9000.00");
  });
});
