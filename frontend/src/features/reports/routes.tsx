import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { parseReportSearch } from "./lib/search";
import { ReportPrintPage } from "./pages/ReportPrintPage";
import { ReportsPage } from "./pages/ReportsPage";
import { ReportViewerPage } from "./pages/ReportViewerPage";

/** reports module routes, mounted under the authenticated app layout. */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const index = createRoute({
    getParentRoute: () => parent,
    path: "/reports",
    component: ReportsPage,
  });
  const viewer = createRoute({
    getParentRoute: () => parent,
    path: "/reports/$reportKey",
    component: ReportViewerPage,
    validateSearch: parseReportSearch,
  });
  const print = createRoute({
    getParentRoute: () => parent,
    path: "/reports/$reportKey/print",
    component: ReportPrintPage,
    validateSearch: parseReportSearch,
  });
  return [index, viewer, print] as const;
}
