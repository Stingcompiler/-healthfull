/*
 * The route tree. ALL feature modules are pre-registered here so feature
 * work only ever edits files inside its own features/<module>/ folder.
 *
 *   root
 *   ├── /login, /sign-in, /change-password  (features/auth; /login is the product page when MARKETING_SITE is on, ADR 0027)
 *   │   (/ without a staff session: the center website when switched on, else the product page, ADR 0028)
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
import { rootPublicView } from "@/lib/site";
import { LazyMarketingPage } from "@/features/marketing/LazyMarketingPage";
import { CenterSiteRoot } from "@/portal/CenterSiteRoot";

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
  const { publicRoot } = appRoute.useRouteContext();
  if (publicRoot === "center") return <CenterSiteRoot />;
  if (publicRoot === "marketing") return <LazyMarketingPage />;
  return <AppLayout />;
}

export const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "_app",
  beforeLoad: async ({ context, location }) => {
    // A visitor with no staff session who opens the site root sees a public page there (ADR 0028
    // decision 4): the center website when the administrator switched it on, else the vendor's
    // product page in marketing mode (ADR 0027), else the sign-in. The session is read first, so
    // a signed-in user never sees a public page flash.
    const publicView = location.pathname === "/" ? rootPublicView() : null;
    if (publicView) {
      const session = await context.queryClient.query({ ...meQueryOptions, staleTime: "static" });
      if (!session) return { publicRoot: publicView };
    }
    const me = await requireAppUser({ context, location });
    if (isKioskOnly(me)) {
      // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router control flow
      throw redirect({ to: "/display/queue" });
    }
    return { publicRoot: null };
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
