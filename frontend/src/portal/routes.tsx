import { createRoute, redirect, type AnyRoute } from "@tanstack/react-router";

import type { RouterContext } from "@/app/router-context";

import { portalMeQuery } from "./api";
import { AppointmentsPage } from "./pages/AppointmentsPage";
import { BookAppointmentPage } from "./pages/BookAppointmentPage";
import { HomePage } from "./pages/HomePage";
import { InvoicePage } from "./pages/InvoicePage";
import { InvoicesPage } from "./pages/InvoicesPage";
import { PortalLoginPage } from "./pages/PortalLoginPage";
import { PrescriptionsPage } from "./pages/PrescriptionsPage";
import { ReceiptPage } from "./pages/ReceiptPage";
import { ResultPage } from "./pages/ResultPage";
import { ResultsPage } from "./pages/ResultsPage";
import { VerifyPage } from "./pages/VerifyPage";
import { PortalAuthedLayout } from "./PortalAuthedLayout";
import { PortalLayout } from "./PortalLayout";

export type PortalLoginReason = "expired" | "signed-out";

export interface PortalLoginSearch {
  reason?: PortalLoginReason;
}

export interface VerifySearch {
  r?: string;
}

/**
 * Patient portal (FEATURES 15.2): public, mobile-first, its own layout under /portal and its
 * own session (never the staff one). /verify/$token is the public receipt check behind the QR
 * printed on every receipt (FEATURES 15.1).
 */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const portal = createRoute({
    getParentRoute: () => parent,
    path: "/portal",
    component: PortalLayout,
  });

  const login = createRoute({
    getParentRoute: () => portal,
    path: "/",
    validateSearch: (search: Record<string, unknown>): PortalLoginSearch =>
      search.reason === "expired" || search.reason === "signed-out" ? { reason: search.reason } : {},
    beforeLoad: async ({ context }) => {
      const me = await (context as RouterContext).queryClient.query({ ...portalMeQuery, staleTime: 0 });
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router control flow
      if (me) throw redirect({ to: "/portal/home" });
    },
    component: PortalLoginPage,
  });

  const authed = createRoute({
    getParentRoute: () => portal,
    id: "portal-signed-in",
    beforeLoad: async ({ context }) => {
      const me = await (context as RouterContext).queryClient.query({ ...portalMeQuery, staleTime: 30_000 });
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router control flow
      if (!me) throw redirect({ to: "/portal", search: { reason: "expired" } });
      return { portalMe: me };
    },
    component: PortalAuthedLayout,
  });

  const home = createRoute({ getParentRoute: () => authed, path: "/home", component: HomePage });
  const appointments = createRoute({
    getParentRoute: () => authed,
    path: "/appointments",
    component: AppointmentsPage,
  });
  const book = createRoute({
    getParentRoute: () => authed,
    path: "/appointments/new",
    component: BookAppointmentPage,
  });
  const results = createRoute({ getParentRoute: () => authed, path: "/results", component: ResultsPage });
  const result = createRoute({ getParentRoute: () => authed, path: "/results/$lineId", component: ResultPage });
  const prescriptions = createRoute({
    getParentRoute: () => authed,
    path: "/prescriptions",
    component: PrescriptionsPage,
  });
  const invoices = createRoute({ getParentRoute: () => authed, path: "/invoices", component: InvoicesPage });
  const invoice = createRoute({
    getParentRoute: () => authed,
    path: "/invoices/$invoiceId",
    component: InvoicePage,
  });
  const receipt = createRoute({
    getParentRoute: () => authed,
    path: "/receipts/$paymentId",
    component: ReceiptPage,
  });

  const verify = createRoute({
    getParentRoute: () => parent,
    path: "/verify/$token",
    validateSearch: (search: Record<string, unknown>): VerifySearch =>
      typeof search.r === "string" && search.r.length <= 40 ? { r: search.r } : {},
    component: VerifyPage,
  });

  return [
    portal.addChildren([
      login,
      authed.addChildren([home, appointments, book, results, result, prescriptions, invoices, invoice, receipt]),
    ]),
    verify,
  ] as const;
}
