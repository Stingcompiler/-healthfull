/** Shared e2e helpers. Specs import from "../helpers". API clients and data factories: ./api.ts. */
export {
  addCoverage,
  ApiError,
  apiAs,
  apiOperation,
  approveInvoice,
  closeShift,
  createInvoice,
  createPatient,
  createVisit,
  disposeApiClients,
  factoryMode,
  fixture,
  FixtureError,
  newApiClient,
  openShift,
  orderLines,
  paidVisit,
  pay,
  registerAdapter,
  seededCatalog,
  unregisterAdapter,
  usesApi,
  type ApiClient,
  type CatalogRef,
  type InvoiceRef,
  type InvoiceResult,
  type PaidVisitResult,
  type PatientRef,
  type PatientResult,
  type PaymentRef,
  type PayResult,
  type QueueEntryRef,
  type ServiceLineRef,
  type ShiftRef,
  type VisitRef,
  type VisitResult,
} from "./api";
export { apiLogin, csrfHeaders, isLoggedIn, login, loginForm, logout, submitLogin } from "./auth";
export { trackConsoleErrors, type ConsoleTracker } from "./console";
export { LANGS, tr, type Lang } from "./i18n";
export { expectNoHorizontalScroll } from "./layout";
export { expectPrefsApplied, setPrefs, THEMES, type Prefs, type Theme } from "./prefs";
export { requirePasswordChange, reseed } from "./seed";
export { snap } from "./snap";
