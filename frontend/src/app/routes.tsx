/*
 * The route tree. ALL feature modules are pre-registered here so feature
 * work only ever edits files inside its own features/<module>/ folder.
 *
 *   root
 *   ├── /login, /sign-in, /change-password  (features/auth; /login is the product page when MARKETING_SITE is on, ADR 0027)
 *   ├── /portal/*                        (portal, mobile-first, public)
 *   ├── /display/queue                   visits: waiting-room kiosk (signed in, no shell)
 *   └── _app  (auth guard + AppShell)
 *       ├── /                            dashboard
 *       ├── /patients                    patients
 *       ├── /queue, /appointments        visits
 *       ├── /clinic                      clinic
 *       ├── /cashier                     cashier
 *       ├── /pharmacy                    pharmacy
 *       ├── /lab                         lab
 *       ├── /nursing                     nursing
 *       ├── /claims                      claims
 *       ├── /reports                     reports
 *       ├── /administration/*            admin (Django admin owns /admin/*)
 *       └── /design                      design system (style guide)
 */
import { createRootRouteWithContext, createRoute, redirect } from "@tanstack/react-router";

import { routes as adminRoutes } from "@/features/admin/routes";
import { routes as authRoutes } from "@/features/auth/routes";
import { routes as cashierRoutes } from "@/features/cashier/routes";
import { routes as claimsRoutes } from "@/features/claims/routes";
import { routes as clinicRoutes } from "@/features/clinic/routes";
import { routes as dashboardRoutes } from "@/features/dashboard/routes";
import { routes as designRoutes } from "@/features/design/routes";
import { routes as labRoutes } from "@/features/lab/routes";
import { routes as nursingRoutes } from "@/features/nursing/routes";
import { routes as patientsRoutes } from "@/features/patients/routes";
import { routes as pharmacyRoutes } from "@/features/pharmacy/routes";
import { routes as reportsRoutes } from "@/features/reports/routes";
import { kioskRoutes as visitsKioskRoutes, routes as visitsRoutes } from "@/features/visits/routes";
import { routes as portalRoutes } from "@/portal/routes";

import { meQueryOptions } from "@/lib/auth/api";
import { isMarketingSite } from "@/lib/site";
import { LazyMarketingPage } from "@/features/marketing/LazyMarketingPage";

import { isKioskOnly, requireAppUser } from "./guards";
import { AppLayout } from "./layouts/AppLayout";
import { RootLayout } from "./layouts/RootLayout";
import { NotFoundPage } from "./pages/NotFoundPage";
import { RouteErrorPage } from "./pages/RouteErrorPage";
import type { RouterContext } from "./router-context";

export const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: RootLayout,
  notFoundComponent: NotFoundPage,
  errorComponent: RouteErrorPage,
});

function AppEntry() {
  const { marketingRoot } = appRoute.useRouteContext();
  return marketingRoot ? <LazyMarketingPage /> : <AppLayout />;
}

export const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "_app",
  beforeLoad: async ({ context, location }) => {
    // Marketing mode (ADR 0027): a visitor with no staff session who opens the site root sees the
    // product page there. The session is read first, so a signed-in user never sees it flash.
    if (isMarketingSite() && location.pathname === "/") {
      const session = await context.queryClient.query({ ...meQueryOptions, staleTime: "static" });
      if (!session) return { marketingRoot: true };
    }
    const me = await requireAppUser({ context, location });
    if (isKioskOnly(me)) {
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router control flow
      throw redirect({ to: "/display/queue" });
    }
    return { marketingRoot: false };
  },
  component: AppEntry,
});

export const routeTree = rootRoute.addChildren([
  ...authRoutes(rootRoute),
  ...portalRoutes(rootRoute),
  ...visitsKioskRoutes(rootRoute),
  appRoute.addChildren([
    ...dashboardRoutes(appRoute),
    ...patientsRoutes(appRoute),
    ...visitsRoutes(appRoute),
    ...clinicRoutes(appRoute),
    ...cashierRoutes(appRoute),
    ...pharmacyRoutes(appRoute),
    ...labRoutes(appRoute),
    ...nursingRoutes(appRoute),
    ...claimsRoutes(appRoute),
    ...reportsRoutes(appRoute),
    ...adminRoutes(appRoute),
    ...designRoutes(appRoute),
  ]),
]);
