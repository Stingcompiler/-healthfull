import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { ClaimsPage } from "./pages/ClaimsPage";

/** claims module routes, mounted under the authenticated app layout. */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const index = createRoute({
    getParentRoute: () => parent,
    path: "/claims",
    component: ClaimsPage,
  });
  return [index] as const;
}
