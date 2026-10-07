import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { PortalLoginPage } from "./pages/PortalLoginPage";
import { PortalLayout } from "./PortalLayout";

/** Patient portal: public, mobile-first, its own layout under /portal. */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const portal = createRoute({
    getParentRoute: () => parent,
    path: "/portal",
    component: PortalLayout,
  });
  const index = createRoute({
    getParentRoute: () => portal,
    path: "/",
    component: PortalLoginPage,
  });
  return [portal.addChildren([index])] as const;
}
