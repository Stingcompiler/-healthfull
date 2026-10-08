import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { AppointmentsPage } from "./pages/AppointmentsPage";
import { QueueDisplayPage } from "./pages/QueueDisplayPage";
import { QueuePage } from "./pages/QueuePage";

interface DisplaySearch {
  department?: number;
}

export function routes<TParent extends AnyRoute>(parent: TParent) {
  const queue = createRoute({
    getParentRoute: () => parent,
    path: "/queue",
    component: QueuePage,
  });
  const display = createRoute({
    getParentRoute: () => parent,
    path: "/queue/display",
    validateSearch: (search: Record<string, unknown>): DisplaySearch => {
      const department = Number(search.department);
      return Number.isInteger(department) && department > 0 ? { department } : {};
    },
    component: QueueDisplayPage,
  });
  const appointments = createRoute({
    getParentRoute: () => parent,
    path: "/appointments",
    component: AppointmentsPage,
  });
  return [queue, display, appointments] as const;
}
