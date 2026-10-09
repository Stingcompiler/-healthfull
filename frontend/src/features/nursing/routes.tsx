import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { BedBoardPage } from "./pages/BedBoardPage";
import { NursingChartPage } from "./pages/NursingChartPage";
import { NursingPage } from "./pages/NursingPage";
import { NursingVisitsPage } from "./pages/NursingVisitsPage";

/** nursing module routes, mounted under the authenticated app layout. */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const index = createRoute({
    getParentRoute: () => parent,
    path: "/nursing",
    component: NursingPage,
  });
  const visits = createRoute({
    getParentRoute: () => parent,
    path: "/nursing/visits",
    component: NursingVisitsPage,
  });
  const chart = createRoute({
    getParentRoute: () => parent,
    path: "/nursing/visits/$visitId",
    component: NursingChartPage,
  });
  const beds = createRoute({
    getParentRoute: () => parent,
    path: "/nursing/beds",
    component: BedBoardPage,
  });
  return [index, visits, chart, beds] as const;
}
