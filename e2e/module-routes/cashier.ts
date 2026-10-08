/**
 * Cashier, billing and shifts screens for the responsive matrix, besides /cashier (listed in
 * e2e/routes.ts). Owned by the cashier module. Screens with parameters share one paid visit
 * (invoice, cash payment and the seed cashier's shift), built once per worker.
 */
import {
  approveInvoice,
  createPatient,
  createVisit,
  fixture,
  orderLines,
  paidVisit,
  type PaidVisitResult,
} from "../helpers";
import { appRoute, type AppRoute } from "../route-kit";

let paid: Promise<PaidVisitResult> | undefined;

function paidOnce(): Promise<PaidVisitResult> {
  paid ??= paidVisit();
  return paid;
}

function required<T>(value: T | null, what: string): T {
  if (value === null) throw new Error(`paidVisit() returned no ${what}`);
  return value;
}

/** A visit on the 70% payer: one approved invoice still owed and one requested line. */
async function deskVisit(): Promise<string> {
  await fixture("cashier_payer", {});
  const { patient } = await createPatient({ payer: "CSH70" });
  const { visit } = await createVisit({ patient });
  await orderLines({ visit, items: [{ service: "PRC-ECG" }, { service: "LAB-CBC" }] });
  await approveInvoice({ visit, services: ["CONS-GEN", "PRC-ECG"] });
  return `/cashier?visit=${String(visit.id)}`;
}

export const routes: readonly AppRoute[] = [
  appRoute("cashier-desk-visit", "/cashier", {
    resolve: deskVisit,
    ready: (page) => page.getByTestId("payment-panel"),
  }),
  appRoute("cashier-shift", "/cashier/shift"),
  appRoute("cashier-shift-report", "/cashier/shifts/$shiftId", {
    resolve: async () => `/cashier/shifts/${String(required((await paidOnce()).shift, "shift").id)}`,
  }),
  appRoute("cashier-review", "/cashier/review"),
  appRoute("cashier-transfers", "/cashier/transfers"),
  appRoute("cashier-credit-notes", "/cashier/credit-notes"),
  appRoute("cashier-refunds", "/cashier/refunds"),
  appRoute("cashier-perform-first", "/cashier/perform-first"),
  appRoute("cashier-receipt", "/cashier/receipts/$paymentId", {
    resolve: async () => `/cashier/receipts/${String(required((await paidOnce()).payment, "payment").id)}`,
  }),
  appRoute("cashier-invoice-print", "/cashier/invoices/$invoiceId/print", {
    resolve: async () => `/cashier/invoices/${String(required((await paidOnce()).invoice, "invoice").id)}/print`,
  }),
];
