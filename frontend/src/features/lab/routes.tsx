import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { LabPage } from "./pages/LabPage";

/** lab module routes, mounted under the authenticated app layout. */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const index = createRoute({
    getParentRoute: () => parent,
    path: "/lab",
    component: LabPage,
  });
  return [index] as const;
}
