import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { PharmacyPage } from "./pages/PharmacyPage";

/** pharmacy module routes, mounted under the authenticated app layout. */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const index = createRoute({
    getParentRoute: () => parent,
    path: "/pharmacy",
    component: PharmacyPage,
  });
  return [index] as const;
}
