import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { parseClaimsSearch } from "./lib/search";
import { AgingPage } from "./pages/AgingPage";
import { BuildClaimPage } from "./pages/BuildClaimPage";
import { ClaimDetailPage } from "./pages/ClaimDetailPage";
import { ClaimListPage } from "./pages/ClaimListPage";
import { ClaimPrintPage } from "./pages/ClaimPrintPage";
import { ClaimsPage } from "./pages/ClaimsPage";
import { PayerPaymentsPage } from "./pages/PayerPaymentsPage";

/** claims module routes, mounted under the authenticated app layout. */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const index = createRoute({
    getParentRoute: () => parent,
    path: "/claims",
    component: ClaimsPage,
  });
  const batches = createRoute({
    getParentRoute: () => parent,
    path: "/claims/batches",
    component: ClaimListPage,
    validateSearch: parseClaimsSearch,
  });
  const build = createRoute({
    getParentRoute: () => parent,
    path: "/claims/new",
    component: BuildClaimPage,
    validateSearch: parseClaimsSearch,
  });
  const payments = createRoute({
    getParentRoute: () => parent,
    path: "/claims/payments",
    component: PayerPaymentsPage,
    validateSearch: parseClaimsSearch,
  });
  const aging = createRoute({ getParentRoute: () => parent, path: "/claims/aging", component: AgingPage });
  const detail = createRoute({
    getParentRoute: () => parent,
    path: "/claims/$claimId",
    component: ClaimDetailPage,
  });
  const print = createRoute({
    getParentRoute: () => parent,
    path: "/claims/$claimId/print",
    component: ClaimPrintPage,
  });
  return [index, batches, build, payments, aging, detail, print] as const;
}
