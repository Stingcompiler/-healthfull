import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { DashboardPage } from "./pages/DashboardPage";

export function routes<TParent extends AnyRoute>(parent: TParent) {
  const index = createRoute({
    getParentRoute: () => parent,
    path: "/",
    component: DashboardPage,
  });
  return [index] as const;
}
