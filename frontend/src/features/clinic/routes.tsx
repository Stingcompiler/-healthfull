import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { ClinicPage } from "./pages/ClinicPage";

/** clinic module routes, mounted under the authenticated app layout. */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const index = createRoute({
    getParentRoute: () => parent,
    path: "/clinic",
    component: ClinicPage,
  });
  return [index] as const;
}
