import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { NursingPage } from "./pages/NursingPage";

/** nursing module routes, mounted under the authenticated app layout. */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const index = createRoute({
    getParentRoute: () => parent,
    path: "/nursing",
    component: NursingPage,
  });
  return [index] as const;
}
