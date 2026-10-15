import { createRoute, lazyRouteComponent, type AnyRoute } from "@tanstack/react-router";

export function routes<TParent extends AnyRoute>(parent: TParent) {
  const design = createRoute({
    getParentRoute: () => parent,
    path: "/design",
    // The style guide is not part of daily work: load it on demand.
    component: lazyRouteComponent(() => import("./DesignSystemPage"), "DesignSystemPage"),
  });
  // DEV ONLY (UI review, phase 1): visual direction exploration. Registered only by the Vite dev
  // server (import.meta.env.DEV is false in `vite build`), so production never ships or serves it.
  const directions = createRoute({
    getParentRoute: () => parent,
    path: "/design/directions",
    validateSearch: (search: Record<string, unknown>): { d?: string } => ({
      d: typeof search.d === "string" ? search.d : undefined,
    }),
    component: lazyRouteComponent(() => import("./directions/DirectionsPage"), "DirectionsPage"),
  });
  return import.meta.env.DEV ? ([design, directions] as const) : ([design] as const);
}
