import { createRouter } from "@tanstack/react-router";

import { createQueryClient } from "@/lib/query";

import { routeTree } from "./routes";

export const queryClient = createQueryClient();

export const router = createRouter({
  routeTree,
  context: { queryClient },
  defaultPreload: "intent",
  // Route loaders read from TanStack Query, which owns caching.
  defaultPreloadStaleTime: 0,
  scrollRestoration: true,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
