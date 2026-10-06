import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { ReportsPage } from "./pages/ReportsPage";

/** reports module routes, mounted under the authenticated app layout. */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const index = createRoute({
    getParentRoute: () => parent,
    path: "/reports",
    component: ReportsPage,
  });
  return [index] as const;
}
