import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { PatientsPage } from "./pages/PatientsPage";

/** patients module routes, mounted under the authenticated app layout. */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const index = createRoute({
    getParentRoute: () => parent,
    path: "/patients",
    component: PatientsPage,
  });
  return [index] as const;
}
