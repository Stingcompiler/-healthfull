/**
 * Patient portal screens for the responsive matrix, besides /portal (the sign-in page, listed
 * in e2e/routes.ts). Owned by the portal module. The signed-in screens open with a portal
 * session (`prepare` signs the fresh page in; the staff session plays no part, so `auth` is
 * false); data comes from one `portal_patient` fixture call per worker. Each `ready` waits for
 * loaded content.
 */
import type { Page } from "@playwright/test";

import { appRoute, type AppRoute } from "../route-kit";
import { screensPatient, signInPortal } from "../tests/portal/kit";

const signedIn = async (page: Page): Promise<void> => {
  await signInPortal(page, await screensPatient());
};

function portalRoute(
  name: string,
  path: string,
  ready: AppRoute["ready"],
  resolve?: (who: Awaited<ReturnType<typeof screensPatient>>) => string,
): AppRoute {
  return appRoute(name, path, {
    auth: false,
    ready,
    prepare: signedIn,
    resolve: async () => {
      const who = await screensPatient();
      return resolve ? resolve(who) : path;
    },
  });
}

export const routes: readonly AppRoute[] = [
  portalRoute("portal-home", "/portal/home", (page) => page.getByTestId("home-balance")),
  portalRoute("portal-appointments", "/portal/appointments", (page) => page.getByTestId("appointment-row").first()),
  portalRoute("portal-book", "/portal/appointments/new", (page) => page.getByTestId("book-doctor").first()),
  portalRoute("portal-results", "/portal/results", (page) => page.getByTestId("result-row").first()),
  portalRoute(
    "portal-result",
    "/portal/results/$lineId",
    (page) => page.getByTestId("result-values"),
    (who) => `/portal/results/${String(who.approved_line)}`,
  ),
  portalRoute("portal-prescriptions", "/portal/prescriptions", (page) => page.getByTestId("prescription-item").first()),
  portalRoute("portal-invoices", "/portal/invoices", (page) => page.getByTestId("receipt-row").first()),
  portalRoute(
    "portal-invoice",
    "/portal/invoices/$invoiceId",
    (page) => page.getByTestId("invoice-detail"),
    (who) => `/portal/invoices/${String(who.invoice.id)}`,
  ),
  portalRoute(
    "portal-receipt",
    "/portal/receipts/$paymentId",
    (page) => page.getByTestId("receipt-detail"),
    (who) => `/portal/receipts/${String(who.payment.id)}`,
  ),
  appRoute("portal-verify", "/verify/$token", {
    auth: false,
    ready: (page) => page.getByTestId("verify-result"),
    resolve: async () => {
      const who = await screensPatient();
      return `/verify/${who.verify_token}?r=${encodeURIComponent(who.payment.number)}`;
    },
  }),
];
