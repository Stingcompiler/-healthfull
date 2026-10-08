import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { PatientImportPage } from "./pages/PatientImportPage";
import { PatientNewPage } from "./pages/PatientNewPage";
import { PatientProfilePage } from "./pages/PatientProfilePage";
import { PatientsPage } from "./pages/PatientsPage";

export interface PatientsSearch {
  /** Search text, e.g. from the global quick search's "show all". */
  q?: string;
}

/** patients module routes, mounted under the authenticated app layout. */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const index = createRoute({
    getParentRoute: () => parent,
    path: "/patients",
    validateSearch: (search: Record<string, unknown>): PatientsSearch => {
      const q = typeof search.q === "string" ? search.q.trim().slice(0, 200) : "";
      return q ? { q } : {};
    },
    component: PatientsPage,
  });
  const importing = createRoute({
    getParentRoute: () => parent,
    path: "/patients/import",
    component: PatientImportPage,
  });
  const create = createRoute({
    getParentRoute: () => parent,
    path: "/patients/new",
    component: PatientNewPage,
  });
  const profile = createRoute({
    getParentRoute: () => parent,
    path: "/patients/$patientId",
    component: PatientProfilePage,
  });
  return [index, create, importing, profile] as const;
}
