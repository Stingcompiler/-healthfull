import { createRoute, redirect, type AnyRoute } from "@tanstack/react-router";

import type { RouterContext } from "@/app/router-context";
import { getSiteConfig } from "@/lib/site";

import { portalMeQuery } from "./api";
import { AppointmentsPage } from "./pages/AppointmentsPage";
import { BookAppointmentPage, RescheduleAppointmentPage } from "./pages/BookAppointmentPage";
import { CenterPage } from "./pages/CenterPage";
import { GuestBookingPage } from "./pages/GuestBookingPage";
import { GuestBookPage } from "./pages/GuestBookPage";
import { HomePage } from "./pages/HomePage";
import { InvoicePage } from "./pages/InvoicePage";
import { InvoicesPage } from "./pages/InvoicesPage";
import { NoticesPage } from "./pages/NoticesPage";
import { PortalLoginPage } from "./pages/PortalLoginPage";
import { PrescriptionsPage } from "./pages/PrescriptionsPage";
import { ReceiptPage } from "./pages/ReceiptPage";
import { ResultPage } from "./pages/ResultPage";
import { ResultsPage } from "./pages/ResultsPage";
import { ServicesOffPage } from "./pages/ServicesOffPage";
import { VerifyPage } from "./pages/VerifyPage";
import { VisitTimelinePage } from "./pages/VisitTimelinePage";
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
 * own session (never the staff one). /portal is the public center page; /portal/sign-in the
 * patient sign-in. /verify/$token is the public receipt check behind the QR
 * printed on every receipt (FEATURES 15.1).
 *
 * The administrator's switches (ADR 0029, plan D4; read from `GET /api/ops/site`, enforced by
 * the server) choose what opens: the website off sends `/portal` to the sign-in while patient
 * sign-in is on, else to a one-line "not available" page; patient sign-in off sends every
 * patient page back to `/portal`; online booking off sends the booking page to the list.
 */
function PortalEntry() {
  return getSiteConfig().centerSite ? <CenterPage /> : <ServicesOffPage />;
}

function requireTracking() {
  // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router control flow
  if (!getSiteConfig().patientTracking) throw redirect({ to: "/portal" });
}

export function routes<TParent extends AnyRoute>(parent: TParent) {
  const portal = createRoute({
    getParentRoute: () => parent,
    path: "/portal",
    component: PortalLayout,
  });

  // The portal's door: the public center page, open with or without a session.
  const center = createRoute({
    getParentRoute: () => portal,
    path: "/",
    beforeLoad: () => {
      const site = getSiteConfig();
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router control flow
      if (!site.centerSite && site.patientTracking) throw redirect({ to: "/portal/sign-in" });
    },
    component: PortalEntry,
  });

  const login = createRoute({
    getParentRoute: () => portal,
    path: "/sign-in",
    validateSearch: (search: Record<string, unknown>): PortalLoginSearch =>
      search.reason === "expired" || search.reason === "signed-out" ? { reason: search.reason } : {},
    beforeLoad: async ({ context }) => {
      requireTracking();
      const me = await (context as RouterContext).queryClient.query({ ...portalMeQuery, staleTime: 0 });
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router control flow
      if (me) throw redirect({ to: "/portal/home" });
    },
    component: PortalLoginPage,
  });

  // Booking without a file (ADR 0029 D, Phase 4b): open while online and guest booking are on.
  // A signed-in patient keeps the booking of their file instead.
  const guestBook = createRoute({
    getParentRoute: () => portal,
    path: "/book",
    beforeLoad: async ({ context }) => {
      const site = getSiteConfig();
      if (site.onlineBooking && site.patientTracking) {
        const me = await (context as RouterContext).queryClient.query({ ...portalMeQuery, staleTime: 30_000 });
        // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router control flow
        if (me) throw redirect({ to: "/portal/appointments/new" });
      }
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router control flow
      if (!site.guestBooking) throw redirect({ to: "/portal" });
    },
    component: GuestBookPage,
  });

  // A guest's one booking, opened with its reference and PIN (needs online booking on).
  const guestBooking = createRoute({
    getParentRoute: () => portal,
    path: "/booking",
    beforeLoad: () => {
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router control flow
      if (!getSiteConfig().onlineBooking) throw redirect({ to: "/portal" });
    },
    component: GuestBookingPage,
  });

  const authed = createRoute({
    getParentRoute: () => portal,
    id: "portal-signed-in",
    beforeLoad: async ({ context }) => {
      requireTracking();
      const me = await (context as RouterContext).queryClient.query({ ...portalMeQuery, staleTime: 30_000 });
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router control flow
      if (!me) throw redirect({ to: "/portal/sign-in", search: { reason: "expired" } });
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
    beforeLoad: () => {
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router control flow
      if (!getSiteConfig().onlineBooking) throw redirect({ to: "/portal/appointments" });
    },
    component: BookAppointmentPage,
  });
  const reschedule = createRoute({
    getParentRoute: () => authed,
    path: "/appointments/$appointmentId/reschedule",
    beforeLoad: () => {
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router control flow
      if (!getSiteConfig().onlineBooking) throw redirect({ to: "/portal/appointments" });
    },
    component: RescheduleAppointmentPage,
  });
  // Patient tracking (public site Phase 5): a visit's timeline and the inbox.
  const visit = createRoute({
    getParentRoute: () => authed,
    path: "/visits/$visitId",
    component: VisitTimelinePage,
  });
  const notices = createRoute({ getParentRoute: () => authed, path: "/notices", component: NoticesPage });
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
      center,
      login,
      guestBook,
      guestBooking,
      authed.addChildren([
        home,
        appointments,
        book,
        reschedule,
        visit,
        notices,
        results,
        result,
        prescriptions,
        invoices,
        invoice,
        receipt,
      ]),
    ]),
    verify,
  ] as const;
}
