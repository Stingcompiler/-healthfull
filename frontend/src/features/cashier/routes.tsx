import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { CashierPage } from "./pages/CashierPage";

/** cashier module routes, mounted under the authenticated app layout. */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const index = createRoute({
    getParentRoute: () => parent,
    path: "/cashier",
    component: CashierPage,
  });
  return [index] as const;
}
