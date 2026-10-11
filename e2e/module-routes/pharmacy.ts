/**
 * Pharmacy screens for the responsive matrix, besides /pharmacy (listed in e2e/routes.ts).
 * Owned by the pharmacy module. The lists are checked with data in them: the seed's opening
 * receipts, near-expiry and low-stock items, plus a paid prescription, a pending adjustment, a
 * draft transfer and an open count in the outpatient pharmacy, built once per worker through
 * the real endpoints. Each `ready` waits for loaded content, never for the heading alone.
 */
import type { Locator, Page } from "@playwright/test";

import { apiAs, approveInvoice, createPatient, createVisit, fixture, orderLines, pay, seededCatalog } from "../helpers";
import { appRoute, type AppRoute } from "../route-kit";

/** The first loaded row of a list: a card on phones, a table row from md up. */
function firstRow(page: Page, cardTestId: string): Locator {
  return page
    .locator(
      `[data-testid="${cardTestId}"], ` +
        '[data-slot="data-table"][data-mode="table"] tbody tr:not(:has([data-slot="skeleton"])):not(:has(td[colspan]))',
    )
    .first();
}

interface Page_<T> {
  items: T[];
}

let paidPrescription: Promise<string> | undefined;

/** A cash patient's paid prescription of paracetamol and ORS: the queue has a row. */
function prescriptionOnce(): Promise<string> {
  paidPrescription ??= (async () => {
    const { patient } = await createPatient();
    const { visit } = await createVisit({ patient, coverage: "cash" });
    await orderLines({
      visit,
      items: [
        { service: "DRG-PARA500", quantity: 20 },
        { service: "DRG-ORS", quantity: 3 },
      ],
    });
    const { invoice } = await approveInvoice({
      visit,
      services: ["DRG-PARA500", "DRG-ORS"],
    });
    await pay({ invoice });
    return visit.number;
  })();
  return paidPrescription;
}

let documents: Promise<{ countId: number }> | undefined;

/** A pending adjustment, a draft transfer and an open count in PHA (reused when open). */
function documentsOnce(): Promise<{ countId: number }> {
  documents ??= (async () => {
    const catalog = await seededCatalog();
    const pharmacist = await apiAs("pharmacist");
    const pha = catalog.stores.PHA;
    const main = catalog.stores.MAIN;
    if (pha === undefined || main === undefined) throw new Error("seeded stores PHA and MAIN are missing");
    const gloves = catalog.items["CNS-GLOVES"]?.batches.at(-1);
    const gauze = catalog.items["CNS-GAUZE"]?.batches.at(-1);
    if (!gloves || !gauze) throw new Error("seeded glove and gauze batches are missing");
    await pharmacist.post("/api/pharmacy/adjustments", {
      store_id: pha,
      reason_code: "DAMAGED",
      note: "Responsive matrix",
      lines: [{ batch_id: gloves.id, qty_base: -1, note: "" }],
    });
    await pharmacist.post("/api/pharmacy/transfers", {
      from_store_id: main,
      to_store_id: pha,
      note: "",
      lines: [{ batch_id: gauze.id, qty_base: 5 }],
    });
    const open = await pharmacist.get<Page_<{ id: number; store: { id: number } }>>(
      "/api/pharmacy/counts?status=open&page_size=100",
    );
    const existing = open.items.find((c) => c.store.id === pha);
    if (existing) return { countId: existing.id };
    const count = await pharmacist.post<{ id: number }>("/api/pharmacy/counts", { store_id: pha, note: "" });
    return { countId: count.id };
  })();
  return documents;
}

let dispensed: Promise<void> | undefined;

/** A paid prescription dispensed from PHA: the returns screen lists it (ADR 0018). */
function dispensedOnce(): Promise<void> {
  dispensed ??= fixture("pharmacy_dispensed", {}).then(() => undefined);
  return dispensed;
}

export const routes: readonly AppRoute[] = [
  appRoute("pharmacy-queue", "/pharmacy", {
    resolve: async () => {
      await prescriptionOnce();
      return "/pharmacy";
    },
    ready: (page) => page.getByTestId("queue-visit").first(),
  }),
  appRoute("pharmacy-sale", "/pharmacy/sale", {
    ready: (page) => page.getByTestId("sale-submit"),
  }),
  appRoute("pharmacy-items", "/pharmacy/items", {
    ready: (page) => firstRow(page, "item-row"),
  }),
  appRoute("pharmacy-item", "/pharmacy/items/$itemId", {
    resolve: async () => {
      const item = (await seededCatalog()).items["DRG-PARA500"];
      if (!item) throw new Error("seeded paracetamol item is missing");
      return `/pharmacy/items/${String(item.id)}`;
    },
    ready: (page) => page.getByTestId("item-summary"),
  }),
  appRoute("pharmacy-receipts", "/pharmacy/receipts", {
    ready: (page) => firstRow(page, "receipt-row"),
  }),
  appRoute("pharmacy-adjustments", "/pharmacy/adjustments", {
    resolve: async () => {
      await documentsOnce();
      return "/pharmacy/adjustments";
    },
    ready: (page) => firstRow(page, "adjustment-row"),
  }),
  appRoute("pharmacy-counts", "/pharmacy/counts", {
    resolve: async () => {
      await documentsOnce();
      return "/pharmacy/counts";
    },
    ready: (page) => firstRow(page, "count-row"),
  }),
  appRoute("pharmacy-count", "/pharmacy/counts/$countId", {
    resolve: async () => `/pharmacy/counts/${String((await documentsOnce()).countId)}`,
    ready: (page) => page.getByTestId("count-line").first(),
  }),
  appRoute("pharmacy-transfers", "/pharmacy/transfers", {
    resolve: async () => {
      await documentsOnce();
      return "/pharmacy/transfers";
    },
    ready: (page) => firstRow(page, "transfer-row"),
  }),
  appRoute("pharmacy-expiry", "/pharmacy/expiry", {
    ready: (page) => firstRow(page, "expiry-row"),
  }),
  appRoute("pharmacy-returns", "/pharmacy/returns", {
    resolve: async () => {
      await dispensedOnce();
      return "/pharmacy/returns";
    },
    ready: (page) => page.getByTestId("returnable-dispense").first(),
  }),
  appRoute("pharmacy-low-stock", "/pharmacy/low-stock", {
    ready: (page) => firstRow(page, "low-stock-row"),
  }),
];
