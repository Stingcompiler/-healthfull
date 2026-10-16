import { createRoute, lazyRouteComponent, type AnyRoute } from "@tanstack/react-router";

export function routes<TParent extends AnyRoute>(parent: TParent) {
  const design = createRoute({
    getParentRoute: () => parent,
    path: "/design",
    // The style guide is not part of daily work: load it on demand.
    component: lazyRouteComponent(() => import("./DesignSystemPage"), "DesignSystemPage"),
  });
  return [design] as const;
}
