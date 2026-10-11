/**
 * Server restart resilience (Phase 8 hardening): money and stock survive a hard kill.
 *
 * The Playwright-managed backend is never touched (later specs need it). This spec spawns a
 * second Django server on its own free port against the same e2e database, drives a visit
 * through its API (patient -> visit -> drug and test orders -> invoices -> cash and a bank
 * transfer), SIGKILLs the whole process group right after the transfer is answered, starts a new
 * server on the same port and carries on (dispense). Then it kills the server again while a cash
 * payment is in flight and proves the payment is all or nothing.
 *
 * What must hold after every restart: each payment exists exactly once (re-posting the transfer
 * reference is refused as DUPLICATE_REFERENCE), invoice outstanding is right, the shift's
 * expected cash and pending transfers match, stock moved exactly once at dispense, and the
 * revenue report's figures moved by exactly this visit's amounts.
 */
import { expect, test } from "@playwright/test";

import { USERS } from "../../fixtures/users";
import { closeShift, disposeApiClients, FixtureError, openShift, seededCatalog, type CatalogRef } from "../../helpers";
import { Backend, freePort, letters, ServerApi, uniquePhone } from "./kit";

interface LineOut {
  id: number;
  service: { code: string };
  state: string;
}
interface InvoiceOut {
  id: number;
  number: string | null;
  status: string;
  patient_total: string;
  outstanding: string | null;
  payments: { payment_id: number; number: string; method: string; verification: string; amount: string }[];
}
interface VisitBillingOut {
  unbilled: LineOut[];
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
  allocations: { invoice_id: number; amount: string }[];
  unallocated: string;
}
interface ShiftReport {
  shift: { id: number; number: string; status: string };
  expected_cash: string;
  movements: { opening_float: string; cash_in: string };
  collection: { cash_confirmed: string; bank_pending: string; confirmed_total: string };
  pending: { number: string; reference: string; amount: string }[];
}
interface Metric {
  key: string;
  value: string | number | null;
}
interface BatchStock {
  batch_id: number;
  store_id: number;
  on_hand: number;
}

const FLOAT = "1000.00";
const CONSULTATION = "15000.00"; // CONS-GEN, cash patient
const DRUG_QTY = 10;
const DRUG = "500.00"; // DRG-PARA500 x 10 at 50
const TEST = "4000.00"; // LAB-FBS

function metric(body: { metrics: Metric[] }, key: string): number {
  return Number(body.metrics.find((m) => m.key === key)?.value ?? Number.NaN);
}

function money(n: number): string {
  return n.toFixed(2);
}

async function noShift(): Promise<void> {
  await openShift({ as: "cashier", if_open: "close" });
  await closeShift({ as: "cashier" });
}

test.describe("@cycle @restart server restart", () => {
  test.describe.configure({ mode: "serial", timeout: 10 * 60_000 });

  let backend: Backend | undefined;
  const sessions: ServerApi[] = [];

  test.afterAll(async () => {
    await backend?.kill();
    for (const s of sessions.splice(0)) await s.dispose().catch(() => undefined);
    await closeShift({ as: "cashier" }).catch((error: unknown) => {
      if (!(error instanceof FixtureError && error.code === "SHIFT_NOT_OPEN")) throw error;
    });
    await disposeApiClients();
  });

  test("@cycle @restart a hard kill loses or duplicates no money and no stock", async () => {
    const catalog: CatalogRef = await seededCatalog();
    const drugService = catalog.services["DRG-PARA500"];
    const testService = catalog.services["LAB-FBS"];
    const item = catalog.items["DRG-PARA500"];
    const pha = catalog.stores.PHA;
    if (!drugService || !testService || !item || pha === undefined) throw new Error("seed catalog incomplete");
    await noShift();

    const server = new Backend(await freePort());
    backend = server;
    await server.start();
    const login = async (who: Parameters<typeof ServerApi.login>[1]) => {
      const s = await ServerApi.login(server.url, who);
      sessions.push(s);
      return s;
    };
    const reception = await login("reception");
    const doctor = await login("doctor");
    const cashier = await login("cashier");
    const pharmacist = await login("pharmacist");
    const manager = await login("manager");
    // The transfer list belongs to who verifies transfers (payments.confirm_transfer): read-only checks.
    const supervisor = await login("cashsup");

    const day = (await manager.get<{ date: string }>("/api/reports/dashboard")).date;
    const revenue = () => manager.get<{ metrics: Metric[] }>(`/api/reports/revenue?date_from=${day}&date_to=${day}`);
    const baseline = await revenue();
    const stock = async () => {
      const detail = await pharmacist.get<{ batches: BatchStock[] }>(`/api/pharmacy/items/${String(item.id)}`);
      return detail.batches.filter((b) => b.store_id === pha).reduce((sum, b) => sum + b.on_hand, 0);
    };

    // ---- server 1: the visit up to the payments ---------------------------------------------
    const patient = await reception.post<{ id: number; file_no: string }>("/api/patients", {
      full_name_en: `Restart ${letters()} Ali`,
      sex: "male",
      phone: uniquePhone(),
      date_of_birth: "1990-02-03",
      confirm_not_duplicate: true,
    });
    const options = await reception.get<{ doctors: { id: number; department_id: number; name_en: string }[] }>(
      "/api/visits/options",
    );
    const gp = options.doctors.find((d) => d.name_en === USERS.doctor.fullNameEn);
    if (!gp) throw new Error("the general practitioner is not offered");
    const { visit } = await reception.post<{ visit: { id: number; number: string } }>("/api/visits", {
      patient_id: patient.id,
      department_id: gp.department_id,
      doctor_id: gp.id,
      visit_type: "new",
      use_default_coverage: true,
    });
    await doctor.post(`/api/orders/visits/${String(visit.id)}/lines`, {
      items: [{ service_id: drugService.id, quantity: DRUG_QTY }, { service_id: testService.id }],
    });

    await cashier.post("/api/payments/shifts", { opening_float: FLOAT });
    const billing = () => cashier.get<VisitBillingOut>(`/api/billing/visits/${String(visit.id)}`);
    const unbilled = (await billing()).unbilled;
    const lineOf = (code: string) => {
      const line = unbilled.find((l) => l.service.code === code);
      if (!line) throw new Error(`no unbilled ${code} line`);
      return line;
    };
    const invoiceFor = async (code: string) => {
      const draft = await cashier.post<InvoiceOut>("/api/billing/invoices", {
        visit_id: visit.id,
        line_ids: [lineOf(code).id],
      });
      return cashier.post<InvoiceOut>(`/api/billing/invoices/${String(draft.id)}/approve`, {});
    };
    const consultation = await invoiceFor("CONS-GEN");
    const drug = await invoiceFor("DRG-PARA500");
    expect([consultation.patient_total, drug.patient_total]).toEqual([CONSULTATION, DRUG]);
    const stockAtStart = await stock();

    const cash = await cashier.post<PaymentOut>("/api/payments/payments", {
      patient_id: patient.id,
      method: "cash",
      amount: CONSULTATION,
      auto: true,
      visit_id: visit.id,
    });
    expect(cash.allocations.map((a) => [a.invoice_id, a.amount])).toEqual([[consultation.id, CONSULTATION]]);
    const reference = `RST${String(Date.now())}`;
    const transfer = await cashier.post<PaymentOut>("/api/payments/payments", {
      patient_id: patient.id,
      method: "bank_transfer",
      bank: "BOK",
      reference,
      amount: DRUG,
      auto: true,
      visit_id: visit.id,
    });
    expect(transfer.verification).toBe("pending");
    expect(transfer.allocations.map((a) => [a.invoice_id, a.amount])).toEqual([[drug.id, DRUG]]);

    // ---- power cut right after the transfer was answered ------------------------------------
    await server.kill();
    await server.start();

    const invoices = async () => new Map((await billing()).invoices.map((i) => [i.id, i]));
    const shift = async () => {
      const current = await cashier.get<{ report: ShiftReport | null }>("/api/payments/shifts/current");
      if (!current.report) throw new Error("the cashier's shift did not survive the restart");
      return current.report;
    };
    const transfersWithRef = async () =>
      (
        await supervisor.get<{ items: { payment: { id: number; reference: string } }[] }>(
          `/api/payments/transfers?q=${encodeURIComponent(reference)}&page_size=50`,
        )
      ).items.filter((t) => t.payment.reference === reference);

    // Each payment exists exactly once, with its allocation.
    let byId = await invoices();
    expect(byId.get(consultation.id)?.outstanding).toBe("0.00");
    expect(byId.get(drug.id)?.outstanding).toBe("0.00");
    expect(byId.get(consultation.id)?.payments.map((p) => p.number)).toEqual([cash.number]);
    expect(byId.get(drug.id)?.payments.map((p) => [p.number, p.verification])).toEqual([[transfer.number, "pending"]]);
    expect((await cashier.get<PaymentOut>(`/api/payments/payments/${String(transfer.id)}`)).unallocated).toBe("0.00");
    expect(await transfersWithRef()).toHaveLength(1);

    // The same reference again (written differently) is refused; nothing is recorded.
    const again = await cashier.send<{ code: string }>("POST", "/api/payments/payments", {
      patient_id: patient.id,
      method: "bank_transfer",
      bank: "BOK",
      reference: ` ${reference.toLowerCase()} `,
      amount: DRUG,
      auto: false,
    });
    expect(again.status).toBe(409);
    expect(again.body.code).toBe("DUPLICATE_REFERENCE");
    expect(await transfersWithRef()).toHaveLength(1);
    const balance = (await billing()).balance;
    expect([balance.outstanding, balance.credit]).toEqual(["0.00", "0.00"]);

    // The shift counts the cash once and the transfer as pending only.
    let report = await shift();
    expect(report.shift.id).toBe(cash.shift_id);
    expect(report.expected_cash).toBe(money(Number(FLOAT) + Number(CONSULTATION)));
    expect(report.collection.cash_confirmed).toBe(CONSULTATION);
    expect(report.collection.bank_pending).toBe(DRUG);
    expect(report.pending.map((p) => p.number)).toEqual([transfer.number]);

    // ---- server 2: dispense -----------------------------------------------------------------
    expect(await stock(), "invoicing and paying moved no stock").toBe(stockAtStart);
    const drugLine = lineOf("DRG-PARA500");
    const dispense = {
      visit_id: visit.id,
      store_id: pha,
      lines: [{ service_line_id: drugLine.id, quantity: DRUG_QTY }],
    };
    await pharmacist.post("/api/pharmacy/dispenses", dispense);
    expect(await stock()).toBe(stockAtStart - DRUG_QTY);
    const twice = await pharmacist.send<{ code: string }>("POST", "/api/pharmacy/dispenses", dispense);
    expect(twice.status, `a second dispense of the same line: ${JSON.stringify(twice.body)}`).toBe(409);
    expect(await stock(), "stock moved exactly once").toBe(stockAtStart - DRUG_QTY);

    // ---- power cut while a cash payment is in flight ----------------------------------------
    const lab = await invoiceFor("LAB-FBS");
    expect(lab.patient_total).toBe(TEST);
    const inFlight = cashier
      .send<PaymentOut>(
        "POST",
        "/api/payments/payments",
        { patient_id: patient.id, method: "cash", amount: TEST, auto: true, visit_id: visit.id },
        15_000,
      )
      .then(
        (answer) => ({ answered: answer.status }),
        (error: unknown) => ({ answered: 0, error: String(error) }),
      );
    await new Promise((r) => setTimeout(r, 25));
    await server.kill();
    const outcome = await inFlight;
    await server.start();

    byId = await invoices();
    const labNow = byId.get(lab.id);
    const recorded = labNow?.payments ?? [];
    const description = `answer ${String(outcome.answered)}, payments recorded ${String(recorded.length)}`;
    test.info().annotations.push({ type: "in-flight kill", description });
    console.log(`restart spec, in-flight kill: ${description}`);
    // All or nothing: one complete payment, or none at all and the invoice still owed.
    expect(recorded.length).toBeLessThanOrEqual(1);
    if (outcome.answered >= 200 && outcome.answered < 300) expect(recorded).toHaveLength(1);
    report = await shift();
    if (recorded.length === 1) {
      expect(recorded[0]?.amount).toBe(TEST);
      expect(labNow?.outstanding).toBe("0.00");
      expect(report.collection.cash_confirmed).toBe(money(Number(CONSULTATION) + Number(TEST)));
    } else {
      expect(labNow?.outstanding).toBe(TEST);
      expect(report.collection.cash_confirmed).toBe(CONSULTATION);
      expect(report.expected_cash).toBe(money(Number(FLOAT) + Number(CONSULTATION)));
      // Nothing was taken: the cashier takes it now, once.
      await cashier.post<PaymentOut>("/api/payments/payments", {
        patient_id: patient.id,
        method: "cash",
        amount: TEST,
        auto: true,
        visit_id: visit.id,
      });
    }

    // ---- final books ------------------------------------------------------------------------
    byId = await invoices();
    expect([...byId.values()].map((i) => i.outstanding)).toEqual(["0.00", "0.00", "0.00"]);
    expect(byId.get(lab.id)?.payments).toHaveLength(1);
    report = await shift();
    expect(report.expected_cash).toBe(money(Number(FLOAT) + Number(CONSULTATION) + Number(TEST)));
    expect(report.movements.cash_in).toBe(money(Number(CONSULTATION) + Number(TEST)));
    expect(report.collection.bank_pending).toBe(DRUG);
    const finalBalance = (await billing()).balance;
    expect([finalBalance.outstanding, finalBalance.credit]).toEqual(["0.00", "0.00"]);
    expect(await stock()).toBe(stockAtStart - DRUG_QTY);

    // The revenue report moved by exactly this visit's money: cash collected, transfer pending.
    const now = await revenue();
    expect(metric(now, "collected") - metric(baseline, "collected")).toBe(Number(CONSULTATION) + Number(TEST));
    expect(metric(now, "cash") - metric(baseline, "cash")).toBe(Number(CONSULTATION) + Number(TEST));
    expect(metric(now, "pending_transfers") - metric(baseline, "pending_transfers")).toBe(Number(DRUG));
    expect(server.starts).toBe(3);
  });
});
