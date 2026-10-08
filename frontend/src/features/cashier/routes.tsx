import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { parseCashierSearch } from "./lib/search";
import { CashierPage } from "./pages/CashierPage";
import { CreditNotesPage } from "./pages/CreditNotesPage";
import { InvoicePrintPage } from "./pages/InvoicePrintPage";
import { PerformFirstPage } from "./pages/PerformFirstPage";
import { ReceiptPage } from "./pages/ReceiptPage";
import { RefundsPage } from "./pages/RefundsPage";
import { ReviewPage } from "./pages/ReviewPage";
import { ShiftDetailPage } from "./pages/ShiftDetailPage";
import { ShiftPage } from "./pages/ShiftPage";
import { TransfersPage } from "./pages/TransfersPage";

/** cashier module routes, mounted under the authenticated app layout. */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const index = createRoute({
    getParentRoute: () => parent,
    path: "/cashier",
    component: CashierPage,
    validateSearch: parseCashierSearch,
  });
  const shift = createRoute({ getParentRoute: () => parent, path: "/cashier/shift", component: ShiftPage });
  const shiftDetail = createRoute({
    getParentRoute: () => parent,
    path: "/cashier/shifts/$shiftId",
    component: ShiftDetailPage,
  });
  const review = createRoute({ getParentRoute: () => parent, path: "/cashier/review", component: ReviewPage });
  const transfers = createRoute({ getParentRoute: () => parent, path: "/cashier/transfers", component: TransfersPage });
  const creditNotes = createRoute({
    getParentRoute: () => parent,
    path: "/cashier/credit-notes",
    component: CreditNotesPage,
  });
  const refunds = createRoute({ getParentRoute: () => parent, path: "/cashier/refunds", component: RefundsPage });
  const performFirst = createRoute({
    getParentRoute: () => parent,
    path: "/cashier/perform-first",
    component: PerformFirstPage,
  });
  const receipt = createRoute({
    getParentRoute: () => parent,
    path: "/cashier/receipts/$paymentId",
    component: ReceiptPage,
  });
  const invoicePrint = createRoute({
    getParentRoute: () => parent,
    path: "/cashier/invoices/$invoiceId/print",
    component: InvoicePrintPage,
  });
  return [
    index,
    shift,
    shiftDetail,
    review,
    transfers,
    creditNotes,
    refunds,
    performFirst,
    receipt,
    invoicePrint,
  ] as const;
}
