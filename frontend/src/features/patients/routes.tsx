import { createRoute, type AnyRoute } from "@tanstack/react-router";

import { PatientNewPage } from "./pages/PatientNewPage";
import { PatientProfilePage } from "./pages/PatientProfilePage";
import { PatientsPage } from "./pages/PatientsPage";

/** patients module routes, mounted under the authenticated app layout. */
export function routes<TParent extends AnyRoute>(parent: TParent) {
  const index = createRoute({
    getParentRoute: () => parent,
    path: "/patients",
    component: PatientsPage,
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
  return [index, create, profile] as const;
}
