/*
 * Bundled translation resources. Every namespace is imported statically so
 * the app never fetches translations at runtime (LAN-only, no CDN).
 * Adding a namespace: create locales/{ar,en}/<ns>.json and add it here; the
 * parity test (i18n.test.ts) then checks it automatically.
 */
import arAdmin from "./locales/ar/admin.json";
import arAuth from "./locales/ar/auth.json";
import arCashier from "./locales/ar/cashier.json";
import arClaims from "./locales/ar/claims.json";
import arClinic from "./locales/ar/clinic.json";
import arCommon from "./locales/ar/common.json";
import arDashboard from "./locales/ar/dashboard.json";
import arDesign from "./locales/ar/design.json";
import arErrors from "./locales/ar/errors.json";
import arLab from "./locales/ar/lab.json";
import arNav from "./locales/ar/nav.json";
import arNursing from "./locales/ar/nursing.json";
import arOps from "./locales/ar/ops.json";
import arPatients from "./locales/ar/patients.json";
import arPharmacy from "./locales/ar/pharmacy.json";
import arPortal from "./locales/ar/portal.json";
import arReports from "./locales/ar/reports.json";
import arVisits from "./locales/ar/visits.json";
import enAdmin from "./locales/en/admin.json";
import enAuth from "./locales/en/auth.json";
import enCashier from "./locales/en/cashier.json";
import enClaims from "./locales/en/claims.json";
import enClinic from "./locales/en/clinic.json";
import enCommon from "./locales/en/common.json";
import enDashboard from "./locales/en/dashboard.json";
import enDesign from "./locales/en/design.json";
import enErrors from "./locales/en/errors.json";
import enLab from "./locales/en/lab.json";
import enNav from "./locales/en/nav.json";
import enNursing from "./locales/en/nursing.json";
import enOps from "./locales/en/ops.json";
import enPatients from "./locales/en/patients.json";
import enPharmacy from "./locales/en/pharmacy.json";
import enPortal from "./locales/en/portal.json";
import enReports from "./locales/en/reports.json";
import enVisits from "./locales/en/visits.json";

export const en = {
  common: enCommon,
  errors: enErrors,
  auth: enAuth,
  nav: enNav,
  design: enDesign,
  dashboard: enDashboard,
  patients: enPatients,
  visits: enVisits,
  clinic: enClinic,
  cashier: enCashier,
  pharmacy: enPharmacy,
  lab: enLab,
  nursing: enNursing,
  claims: enClaims,
  reports: enReports,
  admin: enAdmin,
  ops: enOps,
  portal: enPortal,
} as const;

export const ar = {
  common: arCommon,
  errors: arErrors,
  auth: arAuth,
  nav: arNav,
  design: arDesign,
  dashboard: arDashboard,
  patients: arPatients,
  visits: arVisits,
  clinic: arClinic,
  cashier: arCashier,
  pharmacy: arPharmacy,
  lab: arLab,
  nursing: arNursing,
  claims: arClaims,
  reports: arReports,
  admin: arAdmin,
  ops: arOps,
  portal: arPortal,
} as const;

export const resources = { ar, en } as const;

export type Namespace = keyof typeof en;
export const NAMESPACES = Object.keys(en) as Namespace[];
