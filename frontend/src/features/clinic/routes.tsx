import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { ClinicPage } from "./pages/ClinicPage";
import { PrescriptionPrintPage } from "./pages/PrescriptionPrintPage";
import { ReferralPrintPage } from "./pages/ReferralPrintPage";
import { VisitWorkspacePage } from "./pages/VisitWorkspacePage";
import { parseClinicPrintSearch } from "./print/search";

/** clinic module routes, mounted under the authenticated app layout. */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const index = createRoute({
    getParentRoute: () => parent,
    path: "/clinic",
    component: ClinicPage,
  });
  const workspace = createRoute({
    getParentRoute: () => parent,
    path: "/clinic/visits/$visitId",
    component: VisitWorkspacePage,
  });
  const prescriptionPrint = createRoute({
    getParentRoute: () => parent,
    path: "/clinic/visits/$visitId/prescription/print",
    component: PrescriptionPrintPage,
    validateSearch: parseClinicPrintSearch,
  });
  const referralPrint = createRoute({
    getParentRoute: () => parent,
    path: "/clinic/referrals/$referralId/print",
    component: ReferralPrintPage,
    validateSearch: parseClinicPrintSearch,
  });
  return [index, workspace, prescriptionPrint, referralPrint] as const;
}
