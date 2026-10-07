import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { AppointmentsPage } from "./pages/AppointmentsPage";
import { QueuePage } from "./pages/QueuePage";

export function routes<TParent extends AnyRoute>(parent: TParent) {
  const queue = createRoute({
    getParentRoute: () => parent,
    path: "/queue",
    component: QueuePage,
  });
  const appointments = createRoute({
    getParentRoute: () => parent,
    path: "/appointments",
    component: AppointmentsPage,
  });
  return [queue, appointments] as const;
}
