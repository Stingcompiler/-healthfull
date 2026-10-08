import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { requireAppUser } from "@/app/guards";
import { AuthGuard } from "@/app/layouts/AppLayout";
import type { RouterContext } from "@/app/router-context";

import { AppointmentsPage } from "./pages/AppointmentsPage";
import { QueueDisplayPage } from "./pages/QueueDisplayPage";
import { QueuePage } from "./pages/QueuePage";

interface DisplaySearch {
  department?: number;
}

/** visits module routes, mounted under the authenticated app layout. */
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

function KioskDisplay() {
  return (
    <AuthGuard>
      <QueueDisplayPage />
    </AuthGuard>
  );
}

/**
 * The waiting-room screen as a kiosk page, mounted at the root (outside the app shell): a TV
 * in the waiting room gets no navigation, no quick search and no link into the staff screens.
 */
export function kioskRoutes<TParent extends AnyRoute>(parent: TParent) {
  const display = createRoute({
    getParentRoute: () => parent,
    path: "/display/queue",
    beforeLoad: async ({ context, location }) => {
      await requireAppUser({ context: context as RouterContext, location });
    },
    validateSearch: (search: Record<string, unknown>): DisplaySearch => {
      const department = Number(search.department);
      return Number.isInteger(department) && department > 0 ? { department } : {};
    },
    component: KioskDisplay,
  });
  return [display] as const;
}
