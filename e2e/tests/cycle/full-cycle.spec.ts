/**
 * The whole FLOW.md cycle, role by role, through the real screens (Phase 8 hardening).
 *
 * One AMAN-insured patient (AMAN price list = cash x 0.90, the payer pays 70%):
 *
 *   consultation  CONS-GEN 13,500    payer 9,450.00   patient 4,050.00   cash at step 2
 *   invoice A     LAB-CBC  10,800    payer 7,560.00   patient 3,240.00   ┐ bank transfer 3,780.00,
 *                 PRC-INJ   1,800    payer 1,260.00   patient   540.00   ┘ pending (step 4)
 *   invoice B     DRG-PARA500 x 15     payer   472.50   patient   202.50   cash (step 4)
 *
 * Partial payment of an invoice is off by policy, so the doctor's orders are invoiced as two
 * invoices and the transfer pays invoice A exactly while cash pays invoice B. The cashier closes
 * the shift 52.50 short (expected 2,000 float + 4,050 + 202.50 = 6,252.50, counted 6,200.00);
 * the supervisor then rejects the transfer from their own new shift (reversal booked there,
 * invoice A owed 3,780.00 again); the consultation is credited (cashier drafts, supervisor
 * approves: second person), the released 4,050.00 is refunded (requested by the supervisor's
 * approval, approved by the accountant, paid from the supervisor's shift); the accountant claims
 * AMAN's share of the three remaining lines (9,292.50); the manager finds it all in the reports;
 * the patient signs in to the portal with the code printed on the receipt and reads the result.
 *
 * Every browser context aborts and records requests to hosts other than this machine; the spec
 * ends asserting none was attempted and no console error was logged. API calls only check
 * (money, states, stock) or clean up shared state before and after; every step is a screen.
 */
import { expect, test } from "@playwright/test";

import { USERS } from "../../fixtures/users";
import { apiAs, closeShift, disposeApiClients, FixtureError, openShift, seededCatalog, tr } from "../../helpers";
import { lineRow, lineState, openVisit } from "../cashier/kit";
import { openDispense } from "../pharmacy/kit";
import { fillSignIn } from "../portal/kit";
import { amountOf, reportLoaded, sectionRows } from "../reports/kit";
import { answerOf, choose, letters, sdg, t, uniquePhone, Watch } from "./kit";

// --------------------------------------------------------------------------------------------
// Shapes read back from the API (only the fields the checks use)
// --------------------------------------------------------------------------------------------

interface PatientOut {
  id: number;
  file_no: string;
  phone: string;
  full_name_en: string;
}
interface VisitDetailOut {
  visit: { id: number; number: string; payer: { code: string } | null; card_number: string };
}
interface InvoiceLineOut {
  id: number;
  service: { code: string };
  payer_share: string;
  patient_share: string;
  outstanding: string | null;
  state: string;
}
interface InvoiceOut {
  id: number;
  number: string | null;
  status: string;
  patient_total: string;
  payer_total: string;
  outstanding: string | null;
  lines: InvoiceLineOut[];
  payments: { payment_id: number; number: string; method: string; verification: string; amount: string }[];
}
interface VisitBillingOut {
  invoices: InvoiceOut[];
  balance: { credit: string; spendable: string; pending: string; outstanding: string };
}
interface PaymentOut {
  id: number;
  number: string;
  shift_id: number;
  method: string;
  amount: string;
  verification: string;
  reference: string;
  reversal_number: string | null;
  rejection_reason: { code: string } | null;
  verified_by: { username: string } | null;
}
interface ShiftReport {
  shift: {
    id: number;
    number: string;
    status: string;
    cashier: { username: string };
    expected_cash: string;
    counted_cash: string | null;
    variance: string | null;
    variance_reason: { code: string } | null;
  };
  frozen: boolean;
  expected_cash: string;
  counted_cash: string | null;
  variance: string | null;
  collection: { cash_confirmed: string; bank_pending: string; bank_rejected: string; confirmed_total: string };
  pending: { number: string; reference: string; amount: string }[];
  late_reversals: string;
  refunds_paid: string;
  movements: { opening_float: string; cash_in: string; cash_refunds: string };
}
interface DoctorLine {
  id: number;
  service_code: string;
  status: string;
}
interface BatchStock {
  batch_id: number;
  batch_no: string;
  expiry_date: string;
  store_id: number;
  on_hand: number;
  expired: boolean;
}
interface CreditNoteOut {
  id: number;
  number: string | null;
  status: string;
  invoice_id: number;
  created_by: { username: string } | null;
  approved_by: { username: string } | null;
  patient_total: string;
  payer_total: string;
  released: string;
}
interface RefundOut {
  id: number;
  number: string;
  patient: { id: number };
  amount: string;
  status: string;
  credit_note_id: number | null;
  requested_by: { username: string } | null;
  decided_by: { username: string } | null;
  paid_by: { username: string } | null;
  shift_number: string | null;
}
interface ClaimDetail {
  id: number;
  number: string;
  status: string;
  lines: { invoice_line_id: number; amount_claimed: string; service_code: string; patient: { file_no: string } }[];
}
interface Metric {
  key: string;
  value: string | number | null;
}

function metric(body: { metrics: Metric[] }, key: string): string {
  return String(body.metrics.find((m) => m.key === key)?.value ?? "");
}

// --------------------------------------------------------------------------------------------
// Amounts (see the table above)
// --------------------------------------------------------------------------------------------

const FLOAT = "2000.00";
const CONS = { payer: "9450.00", patient: "4050.00" };
const CBC = { payer: "7560.00", patient: "3240.00" };
const INJ = { payer: "1260.00", patient: "540.00" };
const PARA = { qty: 15, payer: "472.50", patient: "202.50" };
const TRANSFER = "3780.00"; // invoice A's patient share
const EXPECTED = "6252.50"; // float + 4,050 + 202.50
const COUNTED = "6200.00";
const SUP_FLOAT = "5000.00";
const CLAIM_TOTAL = "9292.50"; // 7,560 + 1,260 + 472.50

const NAMES = {
  consultation: "General consultation",
  cbc: "Complete blood count (CBC)",
  injection: "Intramuscular injection",
  paracetamol: "Paracetamol 500 mg tablets",
  aman: /Al-Aman Health Insurance/,
};

/** The cashier and the supervisor start without an open shift (state other specs may leave). */
async function noShift(who: "cashier" | "cashsup"): Promise<void> {
  await openShift({ as: who, if_open: "close" });
  await closeShift({ as: who });
}

test.describe("@cycle full cycle", () => {
  test.describe.configure({ mode: "serial", timeout: 15 * 60_000 });

  test.afterAll(async () => {
    // Leave no till open for the specs that follow (the supervisor's shift holds the refund).
    for (const who of ["cashier", "cashsup"] as const) {
      await closeShift({ as: who }).catch((error: unknown) => {
        if (!(error instanceof FixtureError && error.code === "SHIFT_NOT_OPEN")) throw error;
      });
    }
    await disposeApiClients();
  });

  test("@cycle registration to portal across every role, offline", async ({ browser }) => {
    // Only the logged-out GET /api/auth/me 401 on the login screen is tolerated (trackConsoleErrors).
    const watch = new Watch(browser);
    // The guard is live: a page that reaches for the internet is recorded and refused.
    const probe = new Watch(browser);
    const probePage = await (await probe.context({ width: 375, height: 812 })).newPage();
    await probePage.goto("/login");
    const reached = await probePage.evaluate(() =>
      fetch("https://cdn.example.com/probe.js").then(
        () => true,
        () => false,
      ),
    );
    expect(reached).toBe(false);
    expect(probe.external).toEqual(["GET https://cdn.example.com/probe.js"]);
    await probe.close();
    const catalog = await seededCatalog();
    const para = catalog.items["DRG-PARA500"];
    const phaStore = catalog.stores.PHA;
    if (!para || phaStore === undefined) throw new Error("seeded catalog lacks DRG-PARA500 or the PHA store");
    await noShift("cashier");
    await noShift("cashsup");

    const run = letters();
    const fullName = `Cycle ${run} Osman`;
    const phone = uniquePhone();
    const card = `AMN-${run.toUpperCase()}`;
    const transferRef = `CYC${String(Date.now())}`;

    let patient!: PatientOut;
    let visit!: VisitDetailOut["visit"];
    let consultInvoice!: InvoiceOut;
    let invoiceA!: InvoiceOut;
    let invoiceB!: InvoiceOut;
    let transfer!: PaymentOut;
    let cashierShift!: ShiftReport["shift"];
    let supShiftNumber = "";
    let cbcLine!: DoctorLine;
    let portalCode = "";
    let stockBeforeInvoicing = 0;
    let fefo!: BatchStock;

    const cashier = await watch.staff("cashier");
    const doctor = await watch.staff("doctor");
    const billing = async () =>
      (await apiAs("cashier")).get<VisitBillingOut>(`/api/billing/visits/${String(visit.id)}`);
    const invoice = async (id: number) => {
      const found = (await billing()).invoices.find((i) => i.id === id);
      if (!found) throw new Error(`invoice ${String(id)} not on the visit`);
      return found;
    };
    const paraStock = async () => {
      const item = await (
        await apiAs("pharmacist")
      ).get<{ batches: BatchStock[] }>(`/api/pharmacy/items/${String(para.id)}`);
      return item.batches.filter((b) => b.store_id === phaStore);
    };
    const onHand = (batches: BatchStock[]) => batches.reduce((sum, b) => sum + b.on_hand, 0);

    await test.step("1. reception registers the patient with AMAN cover and opens a GP visit", async () => {
      const page = await watch.staff("reception");
      await page.goto("/patients");
      await page
        .getByRole("link", { name: t("patients:new.open") })
        .first()
        .click();
      await expect(page.locator("#main h1")).toHaveText(t("patients:new.title"));
      await page.getByLabel(t("patients:form.nameEn")).fill(fullName);
      await page.getByRole("radio", { name: t("common:sex.male"), exact: true }).check();
      await page.getByLabel(t("patients:form.dateOfBirth")).fill("1984-05-20");
      await page.getByLabel(t("patients:form.phone"), { exact: true }).fill(phone);
      patient = await answerOf<PatientOut>(page, "POST", /^\/api\/patients$/, () =>
        page.getByRole("button", { name: t("patients:new.submit") }).click(),
      );
      await expect(page).toHaveURL(new RegExp(`/patients/${String(patient.id)}$`));
      await expect(page.locator('[data-slot="patient-card"]')).toContainText(patient.file_no);

      // The insurance card on file.
      await page.getByRole("button", { name: t("patients:coverage.add") }).click();
      const dialog = page.getByRole("dialog");
      await choose(page, t("patients:coverage.payer"), NAMES.aman);
      await dialog.getByLabel(t("patients:coverage.cardNumber")).fill(card);
      await dialog.getByRole("button", { name: t("common:actions.save") }).click();
      await expect(dialog).toHaveCount(0);
      await expect(page.getByTestId("coverage")).toContainText(card);

      // The visit with the general practitioner, on the default coverage (AMAN).
      await page
        .getByRole("button", { name: t("patients:profile.newVisit") })
        .first()
        .click();
      const visitDialog = page.getByRole("dialog");
      await expect(visitDialog.getByTestId("picked-patient")).toContainText(patient.file_no);
      await choose(page, t("visits:create.department"), "General Medicine");
      await choose(page, t("visits:create.doctor"), USERS.doctor.fullNameEn);
      const created = await answerOf<VisitDetailOut>(page, "POST", /^\/api\/visits$/, () =>
        visitDialog.getByRole("button", { name: t("visits:create.submit") }).click(),
      );
      visit = created.visit;
      expect(visit.payer?.code).toBe("AMAN");
      const slip = page.getByRole("dialog");
      await expect(slip.getByTestId("token-slip")).toContainText(patient.file_no);
      await page.keyboard.press("Escape");
      await expect(page.getByTestId("visit-item").first()).toContainText(t("visits:visitStatus.open"));
      await page.context().close();
    });

    await test.step("2. cashier opens the shift and collects the consultation fee", async () => {
      await cashier.goto("/cashier");
      await expect(cashier.getByTestId("shift-bar")).toHaveAttribute("data-shift-status", "none");
      await cashier.getByTestId("open-shift").click();
      const dialog = cashier.getByTestId("open-shift-dialog");
      await dialog.getByLabel(t("cashier:shift.openingFloat")).fill("2000");
      await dialog.getByTestId("open-shift-submit").click();
      await expect(cashier.getByTestId("shift-bar")).toHaveAttribute("data-shift-status", "open");

      await openVisit(cashier, patient.file_no, visit.number);
      const unbilled = cashier.getByTestId("unbilled-lines");
      await expect(unbilled.getByTestId("unbilled-line")).toHaveCount(1);
      await expect(unbilled).toContainText(NAMES.consultation);
      await cashier.getByTestId("create-invoice").click();
      const draft = cashier.getByTestId("draft-invoice");
      const consult = lineRow(draft, NAMES.consultation);
      await expect(consult.getByTestId("payer-share")).toHaveText(sdg(CONS.payer));
      await expect(consult.getByTestId("patient-share")).toHaveText(sdg(CONS.patient));
      consultInvoice = await answerOf<InvoiceOut>(
        cashier,
        "POST",
        /^\/api\/billing\/invoices\/\d+\/approve$/,
        async () => {
          await draft.getByTestId("approve-invoice").click();
          await cashier
            .getByRole("alertdialog")
            .getByRole("button", { name: t("cashier:invoice.approve") })
            .click();
        },
      );
      expect(consultInvoice.number).toMatch(/^INV-/);

      const panel = cashier.getByTestId("payment-panel");
      await expect(panel.getByLabel(t("cashier:payment.amount"))).toHaveValue(CONS.patient);
      await panel.getByTestId("take-payment").click();
      await expect(panel.getByTestId("payment-done")).toContainText(sdg(CONS.patient));
      const card = cashier.locator(`[data-invoice-id="${String(consultInvoice.id)}"]`);
      await expect(card.locator(lineState("paid"))).toHaveCount(1);

      const fee = await invoice(consultInvoice.id);
      expect([fee.payer_total, fee.patient_total, fee.outstanding]).toEqual([CONS.payer, CONS.patient, "0.00"]);
      expect(fee.payments.map((p) => [p.method, p.verification, p.amount])).toEqual([
        ["cash", "confirmed", CONS.patient],
      ]);
    });

    await test.step("3. doctor sees the patient, writes the note and diagnosis, orders and finishes", async () => {
      await doctor.goto("/clinic");
      const entry = doctor.locator(`[data-testid="queue-entry"][data-file-no="${patient.file_no}"]`);
      await expect(entry).toBeVisible();
      await entry.getByRole("link").first().click();
      await expect(doctor).toHaveURL(new RegExp(`/clinic/visits/${String(visit.id)}$`));
      // Call, then start the consultation.
      await doctor.getByTestId("queue-start").click();
      await expect(doctor.getByTestId("queue-start")).toHaveText(new RegExp(t("clinic:queue.start")));
      await doctor.getByTestId("queue-start").click();
      await expect(doctor.getByTestId("queue-complete")).toBeVisible();

      const note = doctor.getByTestId("note-form");
      await note.getByLabel(t("clinic:note.complaint")).fill("Fever and body aches for two days");
      await note.getByLabel(t("clinic:note.examination")).fill("T 38.4, throat congested");
      await note.getByLabel(t("clinic:note.plan")).fill("CBC, antipyretic, one injection");
      await doctor.getByTestId("note-save").click();
      await expect(doctor.getByText(t("clinic:note.savedToast"))).toBeVisible();
      await doctor.getByTestId("icd10-search").fill("malaria");
      await doctor.getByTestId("icd10-results").getByRole("option", { name: /B54/ }).click();
      await doctor.getByTestId("diagnosis-add").click();
      await expect(doctor.getByTestId("diagnosis-list")).toContainText("B54");
      await doctor.getByTestId("note-sign").click();
      await doctor
        .getByRole("alertdialog")
        .getByRole("button", { name: t("clinic:note.sign") })
        .click();
      await expect(doctor.getByTestId("signed-note")).toContainText("Fever and body aches");

      await doctor.getByTestId("tab-orders").click();
      const search = doctor.getByTestId("catalog-search");
      for (const code of ["LAB-CBC", "PRC-INJ", "DRG-PARA500"]) {
        await search.fill(code);
        await expect(doctor.getByTestId("catalog-results").locator(`[data-service-code="${code}"]`)).toBeVisible();
        await expect(search).toHaveAttribute("data-fresh", "true");
        await search.press("Enter");
        await expect(doctor.locator(`[data-testid="draft-item"][data-service-code="${code}"]`)).toBeVisible();
      }
      const rx = doctor.locator('[data-testid="draft-item"][data-service-code="DRG-PARA500"]');
      await rx.getByTestId("rx-frequency").click();
      await doctor.getByTestId("rx-frequency-TID").click();
      await rx.getByTestId("rx-days").fill("5");
      await expect(rx.getByTestId("rx-quantity")).toContainText(String(PARA.qty));
      await doctor.getByTestId("place-orders").click();
      await expect(doctor.locator('[data-testid="order-line"][data-status="requested"]')).toHaveCount(3);
      // The doctor never sees prices.
      await expect(doctor.getByTestId("order-lines")).not.toContainText(/SDG|ج\.س/);

      await doctor.getByTestId("queue-complete").click();
      await doctor
        .getByRole("alertdialog")
        .getByRole("button", { name: t("clinic:queue.complete") })
        .click();
      await expect(doctor.getByTestId("queue-complete")).toBeHidden();

      const lines = await (await apiAs("doctor")).get<DoctorLine[]>(`/api/orders/visits/${String(visit.id)}/lines`);
      const found = lines.find((l) => l.service_code === "LAB-CBC");
      if (!found) throw new Error("the CBC order is not on the visit");
      cbcLine = found;
      expect(
        lines.filter((l) => ["LAB-CBC", "PRC-INJ", "DRG-PARA500"].includes(l.service_code)).map((l) => l.status),
      ).toEqual(["requested", "requested", "requested"]);
      stockBeforeInvoicing = onHand(await paraStock());
    });

    await test.step("4. cashier invoices with the insurance split, takes a pending transfer and cash", async () => {
      await openVisit(cashier, patient.file_no, visit.number);
      const unbilled = cashier.getByTestId("unbilled-lines");
      await expect(unbilled.getByTestId("unbilled-line")).toHaveCount(3);
      // Invoice A: the test and the injection (the paracetamol waits for invoice B).
      await unbilled.getByRole("checkbox", { name: NAMES.paracetamol }).click();
      await cashier.getByTestId("create-invoice").click();
      const draftA = cashier.getByTestId("draft-invoice");
      await expect(lineRow(draftA, NAMES.cbc).getByTestId("payer-share")).toHaveText(sdg(CBC.payer));
      await expect(lineRow(draftA, NAMES.cbc).getByTestId("patient-share")).toHaveText(sdg(CBC.patient));
      await expect(lineRow(draftA, NAMES.injection).getByTestId("payer-share")).toHaveText(sdg(INJ.payer));
      await expect(lineRow(draftA, NAMES.injection).getByTestId("patient-share")).toHaveText(sdg(INJ.patient));
      invoiceA = await answerOf<InvoiceOut>(cashier, "POST", /^\/api\/billing\/invoices\/\d+\/approve$/, async () => {
        await draftA.getByTestId("approve-invoice").click();
        await cashier
          .getByRole("alertdialog")
          .getByRole("button", { name: t("cashier:invoice.approve") })
          .click();
      });
      // Invoice B: the prescription.
      await expect(unbilled.getByTestId("unbilled-line")).toHaveCount(1);
      await cashier.getByTestId("create-invoice").click();
      const draftB = cashier.getByTestId("draft-invoice");
      await expect(lineRow(draftB, NAMES.paracetamol).getByTestId("payer-share")).toHaveText(sdg(PARA.payer));
      await expect(lineRow(draftB, NAMES.paracetamol).getByTestId("patient-share")).toHaveText(sdg(PARA.patient));
      invoiceB = await answerOf<InvoiceOut>(cashier, "POST", /^\/api\/billing\/invoices\/\d+\/approve$/, async () => {
        await draftB.getByTestId("approve-invoice").click();
        await cashier
          .getByRole("alertdialog")
          .getByRole("button", { name: t("cashier:invoice.approve") })
          .click();
      });
      expect([invoiceA.patient_total, invoiceA.payer_total]).toEqual([TRANSFER, "8820.00"]);
      expect([invoiceB.patient_total, invoiceB.payer_total]).toEqual([PARA.patient, PARA.payer]);
      // Invariant 5: invoicing moved no stock.
      expect(onHand(await paraStock())).toBe(stockBeforeInvoicing);

      // Invoice A's patient share by bank transfer: pending verification.
      const panel = cashier.getByTestId("payment-panel");
      await panel.getByTestId("method-bank_transfer").click();
      await choose(cashier, t("cashier:payment.bank"), "Bank of Khartoum (Bankak)");
      await panel.getByLabel(t("cashier:payment.reference")).fill(transferRef);
      await panel.getByLabel(t("cashier:payment.amount")).fill(TRANSFER);
      transfer = await answerOf<PaymentOut>(cashier, "POST", /^\/api\/payments\/payments$/, () =>
        panel.getByTestId("take-payment").click(),
      );
      await expect(panel.getByTestId("payment-done").locator('[data-status="pending_verification"]')).toBeVisible();
      expect([transfer.method, transfer.verification, transfer.amount]).toEqual(["bank_transfer", "pending", TRANSFER]);
      // Pending money settles the lines: the service proceeds (invariant 1 via settlement).
      const cardA = cashier.locator(`[data-invoice-id="${String(invoiceA.id)}"]`);
      await expect(cardA.locator(lineState("paid"))).toHaveCount(2);

      // The rest in cash.
      await expect(panel.getByTestId("method-cash")).toHaveAttribute("data-state", "checked");
      await panel.getByLabel(t("cashier:payment.amount")).fill(PARA.patient);
      const cash = await answerOf<PaymentOut>(cashier, "POST", /^\/api\/payments\/payments$/, () =>
        panel.getByTestId("take-payment").click(),
      );
      expect([cash.method, cash.verification, cash.amount]).toEqual(["cash", "confirmed", PARA.patient]);
      const cardB = cashier.locator(`[data-invoice-id="${String(invoiceB.id)}"]`);
      await expect(cardB.locator(lineState("paid"))).toHaveCount(1);
      await expect(cashier.getByTestId("patient-balance")).toContainText(sdg("0.00"));

      // The receipt carries the portal access code for the patient.
      await panel.getByTestId("print-receipt").click();
      await expect(cashier.getByTestId("receipt-number")).toHaveText(/^RCP-/);
      await cashier.getByTestId("receipt-portal-issue").first().click();
      const printed = cashier.getByTestId("receipt-portal-code-value").first();
      await expect(printed).toHaveText(/^\d{4} \d{4}$/);
      portalCode = (await printed.textContent()) ?? "";

      // Money: both invoices settled, the transfer counted as pending, never as collected.
      const a = await invoice(invoiceA.id);
      const b = await invoice(invoiceB.id);
      expect([a.outstanding, b.outstanding]).toEqual(["0.00", "0.00"]);
      expect(a.payments.map((p) => [p.number, p.verification])).toEqual([[transfer.number, "pending"]]);
      const current = await (
        await apiAs("cashier")
      ).get<{ report: ShiftReport | null }>("/api/payments/shifts/current");
      const report = current.report;
      if (!report) throw new Error("the cashier has no open shift");
      cashierShift = report.shift;
      expect(report.movements.opening_float).toBe(FLOAT);
      expect(report.collection.bank_pending).toBe(TRANSFER);
      expect(report.collection.cash_confirmed).toBe("4252.50");
      expect(report.collection.confirmed_total).toBe("4252.50");
      expect(report.expected_cash).toBe(EXPECTED);
      expect(report.pending.map((p) => p.number)).toEqual([transfer.number]);
    });

    await test.step("5. lab technician receives the sample and enters results; the supervisor approves", async () => {
      const tech = await watch.staff("labtech");
      await tech.goto(`/lab?q=${encodeURIComponent(patient.file_no)}`);
      const row = tech.locator('[data-slot="data-table"] tbody tr').filter({ hasText: patient.file_no });
      await expect(row).toHaveCount(1);
      await expect(row.locator('[data-slot="lab-stage"]')).toHaveAttribute("data-stage", "to_collect");
      await row.getByRole("button").first().click();
      await expect(tech).toHaveURL(new RegExp(`/lab/results/${String(cbcLine.id)}$`));
      await tech.getByTestId("receive-sample").click();
      await tech.getByTestId("confirm-receive").click();
      await expect(tech.getByTestId("accession-no")).toBeVisible();
      const entry = tech.getByTestId("result-entry");
      await entry.getByTestId("value-WBC").fill("6.8");
      await entry.getByTestId("value-HGB").fill("14.2");
      await entry.getByTestId("value-PLT").fill("260");
      await entry.getByTestId("save-results").click();
      await expect(tech.locator('[data-slot="lab-stage"]').first()).toHaveAttribute("data-stage", "to_approve");
      await expect(tech.getByTestId("approval-panel")).toHaveCount(0);
      await tech.context().close();

      const sup = await watch.staff("labsup");
      await sup.goto("/lab/approve");
      const queued = sup.locator('[data-slot="data-table"] tbody tr').filter({ hasText: patient.file_no });
      await queued.getByRole("button").first().click();
      await expect(sup.getByTestId("approval-panel")).toBeVisible();
      await sup.getByTestId("approve-result").click();
      await sup
        .getByRole("button", { name: t("lab:approve.submit") })
        .last()
        .click();
      await expect(sup.locator('[data-slot="lab-stage"]').first()).toHaveAttribute("data-stage", "done");
      await sup.context().close();
    });

    await test.step("6. nurse marks the injection done", async () => {
      const nurse = await watch.staff("nurse", 768);
      await nurse.goto("/nursing");
      const card = nurse.locator('[data-testid="procedure-card"]').filter({ hasText: patient.file_no });
      await expect(card).toHaveCount(1);
      await card.getByTestId("procedure-done").click();
      await expect(card.getByTestId("procedure-undo")).toBeVisible();
      await expect(card).toHaveCount(0, { timeout: 15_000 });
      await expect(nurse.getByTestId("procedures-done")).toContainText(patient.file_no);
      await nurse.context().close();
    });

    await test.step("7. pharmacist dispenses the prescription from the earliest-expiring batch", async () => {
      // FEFO computed independently from the stock: earliest expiry, usable, positive on hand.
      const before = await paraStock();
      const usable = before
        .filter((b) => b.on_hand > 0 && !b.expired)
        .sort((x, y) => x.expiry_date.localeCompare(y.expiry_date) || x.batch_id - y.batch_id);
      const first = usable[0];
      if (!first) throw new Error("no usable paracetamol batch in the pharmacy");
      expect(first.on_hand, "the FEFO batch covers the prescription").toBeGreaterThanOrEqual(PARA.qty);
      fefo = first;

      const page = await watch.staff("pharmacist");
      const dialog = await openDispense(page, visit.number);
      const suggested = dialog.locator('[data-testid="dispense-batch"][data-suggested="true"]');
      await expect(suggested).toHaveCount(1);
      await expect(suggested).toHaveAttribute("data-batch-no", fefo.batch_no);
      await dialog.getByTestId("dispense-submit").click();
      const done = dialog.getByTestId("dispense-done");
      await expect(done.getByTestId("dispensed-batch")).toHaveText([fefo.batch_no]);
      await done.getByTestId("dispense-close").click();
      await page.context().close();

      // Invariant 5: stock moved at dispense, exactly once, from that batch.
      const after = await paraStock();
      expect(onHand(after)).toBe(onHand(before) - PARA.qty);
      expect(after.find((b) => b.batch_id === fefo.batch_id)?.on_hand).toBe(fefo.on_hand - PARA.qty);
    });

    await test.step("8. doctor reads the approved result on the visit", async () => {
      await doctor.goto(`/clinic/visits/${String(visit.id)}`);
      await doctor.getByTestId("tab-results").click();
      const result = doctor.getByTestId("result-card").first();
      await expect(result).toBeVisible();
      await expect(result).toContainText("14.2");
      const lines = await (await apiAs("doctor")).get<DoctorLine[]>(`/api/orders/visits/${String(visit.id)}/lines`);
      expect(Object.fromEntries(lines.map((l) => [l.service_code, l.status]))).toMatchObject({
        "LAB-CBC": "done",
        "PRC-INJ": "done",
        "DRG-PARA500": "done",
      });
    });

    await test.step("9. cashier closes the shift 52.50 short with a reason", async () => {
      await cashier.goto("/cashier/shift");
      await expect(cashier.getByTestId("report-bank-pending")).toContainText(sdg(TRANSFER));
      await expect(cashier.getByTestId("report-confirmed-total")).toContainText(sdg("4252.50"));
      await cashier.getByLabel(t("cashier:close.counted")).fill(COUNTED);
      await expect(cashier.getByTestId("close-shift-form")).toContainText(sdg("52.50"));
      await choose(cashier, t("cashier:close.reason"), "Counting error");
      await cashier
        .getByTestId("close-shift-form")
        .getByLabel(tr("en", "reason.note"))
        .fill("Coins short in the drawer");
      await cashier.getByTestId("close-shift").click();
      await cashier
        .getByRole("alertdialog")
        .getByRole("button", { name: t("cashier:close.submit") })
        .click();
      await expect(cashier.getByTestId("shift-report")).toHaveAttribute("data-frozen", "true");
      await expect(cashier.getByTestId("report-variance")).toContainText(sdg("52.50"));

      const closed = await (await apiAs("cashier")).get<ShiftReport>(`/api/payments/shifts/${String(cashierShift.id)}`);
      expect(closed.frozen).toBe(true);
      expect([closed.shift.status, closed.expected_cash, closed.counted_cash, closed.variance]).toEqual([
        "closed",
        EXPECTED,
        COUNTED,
        "-52.50",
      ]);
      expect(closed.shift.variance_reason?.code).toBe("COUNTING_ERROR");
      expect(closed.collection.bank_pending).toBe(TRANSFER);
    });

    await test.step("10. supervisor opens a shift and rejects the transfer after the close", async () => {
      const sup = await watch.staff("cashsup");
      await sup.goto("/cashier");
      await expect(sup.getByTestId("shift-bar")).toHaveAttribute("data-shift-status", "none");
      await sup.getByTestId("open-shift").click();
      const dialog = sup.getByTestId("open-shift-dialog");
      await dialog.getByLabel(t("cashier:shift.openingFloat")).fill("5000");
      await dialog.getByTestId("open-shift-submit").click();
      await expect(sup.getByTestId("shift-bar")).toHaveAttribute("data-shift-status", "open");
      supShiftNumber = ((await sup.getByTestId("shift-number").textContent()) ?? "").trim();
      expect(supShiftNumber).toMatch(/^SH-/);

      await sup.goto("/cashier/transfers");
      const row = sup.locator("tr").filter({ hasText: transferRef });
      await expect(row).toContainText(t("cashier:shift.status.closed"));
      await row.getByRole("button", { name: tr("en", "table.rowActions") }).click();
      await sup.getByRole("menuitem", { name: t("cashier:transfers.reject") }).click();
      await choose(sup, tr("en", "reason.code"), "Money not received");
      await sup
        .getByRole("dialog")
        .getByRole("button", { name: t("cashier:transfers.reject") })
        .click();
      await expect(sup.getByTestId("rejection-outcome")).toContainText(supShiftNumber);
      await expect(row).toHaveCount(0);

      // The reversal is booked in the supervisor's open shift, linked to the original payment.
      const api = await apiAs("cashsup");
      const original = await api.get<PaymentOut>(`/api/payments/payments/${String(transfer.id)}`);
      expect(original.verification).toBe("rejected");
      expect(original.rejection_reason?.code).toBeTruthy();
      expect(original.reversal_number).toBeTruthy();
      expect(original.shift_id).toBe(cashierShift.id);
      const supShift = await api.get<{ report: ShiftReport | null }>("/api/payments/shifts/current");
      expect(supShift.report?.shift.number).toBe(supShiftNumber);
      expect(supShift.report?.late_reversals).toBe(TRANSFER);
      expect(supShift.report?.expected_cash).toBe(SUP_FLOAT);
      await sup.goto("/cashier/shift");
      await expect(sup.getByTestId("report-late-reversals")).toContainText(sdg(TRANSFER));
      // The closed shift never changes (invariant 3); invoice A is owed again.
      const closed = await api.get<ShiftReport>(`/api/payments/shifts/${String(cashierShift.id)}`);
      expect([closed.expected_cash, closed.variance, closed.collection.bank_pending]).toEqual([
        EXPECTED,
        "-52.50",
        TRANSFER,
      ]);
      const a = await invoice(invoiceA.id);
      expect(a.outstanding).toBe(TRANSFER);
      expect(a.lines.map((l) => l.outstanding)).toEqual([CBC.patient, INJ.patient]);
      expect((await invoice(invoiceB.id)).outstanding).toBe("0.00");
      await sup.context().close();
    });

    await test.step("11. credit note by two people, refund by two people, paid from an open shift", async () => {
      // The cashier drafts a credit note for the consultation.
      await openVisit(cashier, patient.file_no, visit.number);
      const card = cashier.locator(`[data-invoice-id="${String(consultInvoice.id)}"]`);
      await card.getByTestId("open-credit-note").click();
      const dialog = cashier.getByTestId("credit-note-dialog");
      await choose(cashier, tr("en", "reason.code"), "Service cancelled");
      await dialog.locator("[data-testid^=credit-qty-]").first().fill("1");
      const drafted = await answerOf<CreditNoteOut>(
        cashier,
        "POST",
        /^\/api\/billing\/invoices\/\d+\/credit-notes$/,
        () => dialog.getByRole("button", { name: t("cashier:creditNote.submit") }).click(),
      );
      await expect(dialog.getByText(t("cashier:creditNote.createdTitle"))).toBeVisible();
      await dialog
        .getByRole("button", { name: tr("en", "actions.close") })
        .first()
        .click();
      expect(drafted.status).toBe("draft");

      // The supervisor approves it (never the drafter); the released money opens a refund.
      const sup = await watch.staff("cashsup");
      await sup.goto("/cashier/credit-notes");
      const noteRow = sup.locator("tr").filter({ hasText: consultInvoice.number ?? "" });
      await noteRow.getByRole("button", { name: tr("en", "table.rowActions") }).click();
      await sup.getByRole("menuitem", { name: t("cashier:creditNotes.approve") }).click();
      await sup.getByTestId("approve-credit-note").click();
      await expect(noteRow).toHaveCount(0);
      const api = await apiAs("cashsup");
      const note = await api.get<CreditNoteOut>(`/api/billing/credit-notes/${String(drafted.id)}`);
      expect(note.status).toBe("approved");
      expect(note.created_by?.username).toBe("cashier");
      expect(note.approved_by?.username).toBe("cashsup");
      expect([note.patient_total, note.payer_total, note.released]).toEqual([CONS.patient, CONS.payer, CONS.patient]);

      // The accountant approves the refund the supervisor's approval requested.
      const accountant = await watch.staff("accountant");
      await accountant.goto("/cashier/refunds");
      const refundRow = accountant.locator("tr").filter({ hasText: patient.full_name_en });
      await expect(refundRow).toContainText(sdg(CONS.patient));
      await refundRow.getByRole("button", { name: tr("en", "table.rowActions") }).click();
      await accountant.getByRole("menuitem", { name: t("cashier:refunds.approve") }).click();
      await accountant
        .getByRole("dialog")
        .getByRole("button", { name: t("cashier:refunds.approve") })
        .click();
      await expect(refundRow).toHaveCount(0);
      await accountant.context().close();

      // The supervisor pays it in cash from their open shift.
      await sup.goto("/cashier/refunds");
      await sup.getByRole("tab", { name: t("cashier:refunds.status.approved") }).click();
      const payRow = sup.locator("tr").filter({ hasText: patient.full_name_en });
      await payRow.getByRole("button", { name: tr("en", "table.rowActions") }).click();
      await sup.getByRole("menuitem", { name: t("cashier:refunds.pay") }).click();
      await sup
        .getByRole("alertdialog")
        .getByRole("button", { name: t("cashier:refunds.pay") })
        .click();
      await expect(payRow).toHaveCount(0);
      await sup.goto("/cashier/shift");
      await expect(sup.getByTestId("shift-report")).toContainText(t("cashier:report.refundsPaid"));
      await sup.context().close();

      const refunds = await api.get<{ items: RefundOut[] }>(
        `/api/payments/refunds?status=paid&q=${encodeURIComponent(patient.file_no)}&page_size=50`,
      );
      const mine = refunds.items.filter((r) => r.patient.id === patient.id);
      expect(mine).toHaveLength(1);
      const refund = mine[0];
      expect(refund?.amount).toBe(CONS.patient);
      expect(refund?.credit_note_id).toBe(drafted.id);
      expect(refund?.requested_by?.username).toBe("cashsup");
      expect(refund?.decided_by?.username).toBe("accountant");
      expect(refund?.paid_by?.username).toBe("cashsup");
      expect(refund?.shift_number).toBe(supShiftNumber);
      const supShift = await api.get<{ report: ShiftReport | null }>("/api/payments/shifts/current");
      expect(supShift.report?.refunds_paid).toBe(CONS.patient);
      expect(supShift.report?.expected_cash).toBe("950.00");
      const after = await billing();
      expect(after.balance.credit).toBe("0.00");
      expect(after.balance.outstanding).toBe(TRANSFER);
    });

    let claimNumber = "";
    await test.step("12. accountant claims AMAN's share of this visit", async () => {
      const aman = catalog.payers.AMAN;
      if (!aman) throw new Error("AMAN is not seeded");
      const page = await watch.staff("accountant");
      await page.goto(`/claims/new?payer=${String(aman.id)}`);
      const lines = page.getByTestId("accrued-line");
      const ours = lines.filter({ hasText: patient.file_no });
      // The credited consultation owes the payer nothing: only the three other lines accrue.
      await expect(ours).toHaveCount(3);
      await page.getByTestId("build-select-all").click(); // none
      for (let i = 0; i < 3; i += 1) await ours.nth(i).getByRole("checkbox").click();
      await expect(page.getByTestId("build-total")).toContainText(sdg(CLAIM_TOTAL));
      const built = await answerOf<ClaimDetail>(page, "POST", /^\/api\/claims\/batches$/, () =>
        page.getByTestId("build-submit").click(),
      );
      await expect(page).toHaveURL(new RegExp(`/claims/${String(built.id)}$`));
      await expect(page.getByTestId("claim-totals")).toContainText(sdg(CLAIM_TOTAL));
      claimNumber = built.number;
      expect(claimNumber).toMatch(/^CLM-/);
      await page.getByTestId("claim-submit").click();
      await page
        .getByRole("alertdialog")
        .getByRole("button", { name: t("claims:detail.submit") })
        .click();
      await expect(page.locator('[data-status="submitted"]').first()).toBeVisible();
      await page.context().close();

      const claim = await (await apiAs("accountant")).get<ClaimDetail>(`/api/claims/batches/${String(built.id)}`);
      expect(claim.status).toBe("submitted");
      expect(claim.lines.map((l) => [l.service_code, l.amount_claimed]).sort()).toEqual([
        ["DRG-PARA500", PARA.payer],
        ["LAB-CBC", CBC.payer],
        ["PRC-INJ", INJ.payer],
      ]);
      expect(new Set(claim.lines.map((l) => l.patient.file_no))).toEqual(new Set([patient.file_no]));
    });

    await test.step("13. manager sees the day in the reports and on the dashboard", async () => {
      const manager = await apiAs("manager");
      const dashboard = await manager.get<{ date: string; metrics: Metric[] }>("/api/reports/dashboard");
      const day = dashboard.date;
      const revenue = await manager.get<{ metrics: Metric[] }>(`/api/reports/revenue?date_from=${day}&date_to=${day}`);
      const page = await watch.staff("manager");

      await page.goto(`/reports/shift_variances?from=${day}&to=${day}`);
      await reportLoaded(page);
      const shiftRow = sectionRows(page, "shifts").filter({ hasText: cashierShift.number });
      await expect(shiftRow).toHaveCount(1);
      await expect(shiftRow).toContainText(sdg("52.50"));
      await expect(shiftRow).toContainText("Counting error");

      await page.goto(`/reports/adjustments?from=${day}&to=${day}`);
      await reportLoaded(page);
      await page.getByTestId("search-detail").fill(patient.file_no);
      const adjustments = sectionRows(page, "detail").filter({ hasText: patient.file_no });
      await expect(adjustments).toHaveCount(2); // the credit note and the refund
      await expect(adjustments.filter({ hasText: /CN-/ })).toContainText(sdg("13500.00"));
      await expect(adjustments.filter({ hasText: /RFD-/ })).toContainText(sdg(CONS.patient));

      await page.goto(`/reports/revenue?from=${day}&to=${day}`);
      await reportLoaded(page);
      await expect(page.getByTestId("report-metrics")).toContainText("Transfers pending verification");

      await page.goto("/");
      await expect(page.getByTestId("manager-dashboard")).toBeVisible();
      const collected = page
        .locator('[data-slot="kpi-card"]')
        .filter({ hasText: t("dashboard:kpi.collectedToday") })
        .locator('[data-slot="money"]')
        .first();
      await expect.poll(() => amountOf(collected)).toBe(metric(revenue, "collected"));
      expect(metric(dashboard, "collected_today")).toBe(metric(revenue, "collected"));
      // Pending money is never inside the collected figure.
      expect(Number(metric(revenue, "collected"))).toBe(
        Number(metric(revenue, "cash")) + Number(metric(revenue, "bank_confirmed")),
      );
      await page.context().close();
    });

    await test.step("14. the patient signs in to the portal with the receipt's code and reads the result", async () => {
      const page = await watch.phone();
      await page.goto("/portal/sign-in");
      await fillSignIn(page, patient.file_no, patient.phone, portalCode);
      await expect(page).toHaveURL(/\/portal\/home$/);
      await expect(page.getByText(patient.file_no)).toBeVisible();
      await page.goto("/portal/results");
      const row = page.locator(`[data-testid="result-row"][data-line="${String(cbcLine.id)}"]`);
      await expect(row).toBeVisible();
      await row.click();
      const values = page.getByTestId("result-values");
      await expect(values).toBeVisible();
      await expect(values).toContainText("14.2");
      await page.context().close();
    });

    await cashier.context().close();
    await doctor.context().close();
    await watch.close();
    expect(watch.external, "requests to non-local origins").toEqual([]);
    expect(watch.errors(), "console errors / page errors").toEqual([]);
  });
});
