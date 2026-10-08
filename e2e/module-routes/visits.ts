/**
 * Visits, queue and appointments screens for the responsive matrix, besides /queue and
 * /appointments (listed in e2e/routes.ts). Owned by the visits module.
 */
import { appRoute, type AppRoute } from "../route-kit";

export const routes: readonly AppRoute[] = [
  // The waiting-room kiosk lives outside the app shell (no #main): ready once the feed loaded.
  appRoute("queue-display", "/display/queue", {
    ready: (page) => page.locator('[data-testid="queue-display"] #display-now'),
  }),
];
