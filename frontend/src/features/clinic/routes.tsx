import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { ClinicPage } from "./pages/ClinicPage";
import { VisitWorkspacePage } from "./pages/VisitWorkspacePage";

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
  return [index, workspace] as const;
}
