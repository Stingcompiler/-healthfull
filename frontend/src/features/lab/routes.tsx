import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { parseLabelSearch, parsePrintSearch, parseWorklistSearch } from "./lib/search";
import { ApprovePage } from "./pages/ApprovePage";
import { CatalogPage } from "./pages/CatalogPage";
import { LabelPage } from "./pages/LabelPage";
import { LabPage } from "./pages/LabPage";
import { ResultPage } from "./pages/ResultPage";
import { ResultPrintPage } from "./pages/ResultPrintPage";
import { TatPage } from "./pages/TatPage";
import { TestEditorPage } from "./pages/TestEditorPage";

/** lab module routes, mounted under the authenticated app layout. */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const index = createRoute({
    getParentRoute: () => parent,
    path: "/lab",
    component: LabPage,
    validateSearch: parseWorklistSearch,
  });
  const result = createRoute({ getParentRoute: () => parent, path: "/lab/results/$lineId", component: ResultPage });
  const print = createRoute({
    getParentRoute: () => parent,
    path: "/lab/results/$lineId/print",
    component: ResultPrintPage,
    validateSearch: parsePrintSearch,
  });
  const label = createRoute({
    getParentRoute: () => parent,
    path: "/lab/samples/$sampleId/label",
    component: LabelPage,
    validateSearch: parseLabelSearch,
  });
  const approve = createRoute({ getParentRoute: () => parent, path: "/lab/approve", component: ApprovePage });
  const catalog = createRoute({ getParentRoute: () => parent, path: "/lab/catalog", component: CatalogPage });
  const testEditor = createRoute({
    getParentRoute: () => parent,
    path: "/lab/catalog/$testId",
    component: TestEditorPage,
  });
  const tat = createRoute({ getParentRoute: () => parent, path: "/lab/tat", component: TatPage });
  return [index, result, print, label, approve, catalog, testEditor, tat] as const;
}
