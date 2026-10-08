/**
 * Cashier, billing and shifts screens for the responsive matrix, besides /cashier (listed in
 * e2e/routes.ts). Owned by the cashier module. Screens with parameters share one paid visit
 * (invoice, cash payment and the seed cashier's shift), built once per worker. The queues and
 * shift screens are checked with data in them (backend fixture `cashier_screens`, built once
 * for the run as the e2e admin, who views the matrix): each `ready` waits for loaded content,
 * never for the page heading alone (it renders before the data).
 */
import type { Locator, Page } from "@playwright/test";

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

interface Screens {
  open_shift: number;
  closed_shift: number;
  transfer: { id: number; number: string };
}

let screens: Promise<Screens> | undefined;

function screensOnce(): Promise<Screens> {
  screens ??= fixture<Screens>("cashier_screens", {});
  return screens;
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
  await orderLines({
    visit,
    items: [{ service: "PRC-ECG" }, { service: "LAB-CBC" }],
  });
  await approveInvoice({ visit, services: ["CONS-GEN", "PRC-ECG"] });
  return `/cashier?visit=${String(visit.id)}`;
}

/** The first loaded row of a cashier queue: a card on phones, a table row from md up. */
function firstRow(page: Page, cardTestId: string): Locator {
  return page
    .locator(
      `[data-testid="${cardTestId}"], ` +
        '[data-slot="data-table"][data-mode="table"] tbody tr:not(:has([data-slot="skeleton"])):not(:has(td[colspan]))',
    )
    .first();
}

export const routes: readonly AppRoute[] = [
  appRoute("cashier-desk-visit", "/cashier", {
    resolve: deskVisit,
    ready: (page) => page.getByTestId("payment-panel"),
  }),
  // The admin's open shift: report, a handover to the safe in transit, the close form.
  appRoute("cashier-shift", "/cashier/shift", {
    resolve: async () => {
      await screensOnce();
      return "/cashier/shift";
    },
    ready: (page) => page.getByTestId("handovers-in-transit"),
  }),
  appRoute("cashier-shift-report", "/cashier/shifts/$shiftId", {
    resolve: async () => `/cashier/shifts/${String(required((await paidOnce()).shift, "shift").id)}`,
    ready: (page) => page.getByTestId("shift-report"),
  }),
  // A closed shift with a variance, unreviewed: the manager's sign-off form shows.
  appRoute("cashier-shift-signoff", "/cashier/shifts/$shiftId", {
    resolve: async () => `/cashier/shifts/${String((await screensOnce()).closed_shift)}`,
    ready: (page) => page.getByTestId("review-form"),
  }),
  appRoute("cashier-review", "/cashier/review", {
    resolve: async () => {
      await screensOnce();
      return "/cashier/review";
    },
    ready: (page) => firstRow(page, "shift-row"),
  }),
  appRoute("cashier-transfers", "/cashier/transfers", {
    resolve: async () => {
      await screensOnce();
      return "/cashier/transfers";
    },
    ready: (page) => page.getByTestId("transfer-sender").first(),
  }),
  appRoute("cashier-credit-notes", "/cashier/credit-notes", {
    resolve: async () => {
      await screensOnce();
      return "/cashier/credit-notes";
    },
    ready: (page) => firstRow(page, "credit-note-row"),
  }),
  appRoute("cashier-refunds", "/cashier/refunds", {
    resolve: async () => {
      await screensOnce();
      return "/cashier/refunds";
    },
    ready: (page) => firstRow(page, "refund-row"),
  }),
  appRoute("cashier-perform-first", "/cashier/perform-first"),
  appRoute("cashier-receipt", "/cashier/receipts/$paymentId", {
    resolve: async () => `/cashier/receipts/${String(required((await paidOnce()).payment, "payment").id)}`,
    ready: (page) => page.getByTestId("receipt"),
  }),
  appRoute("cashier-receipt-check", "/cashier/receipt-check", {
    resolve: async () => {
      const { transfer } = await screensOnce();
      return `/cashier/receipt-check?q=${encodeURIComponent(transfer.number)}`;
    },
    ready: (page) => page.getByTestId("receipt-check-result"),
  }),
  appRoute("cashier-invoice-print", "/cashier/invoices/$invoiceId/print", {
    resolve: async () => `/cashier/invoices/${String(required((await paidOnce()).invoice, "invoice").id)}/print`,
    ready: (page) => page.getByTestId("invoice-print"),
  }),
];
