/** Shared e2e helpers. Specs import from "../helpers". */
export { apiLogin, csrfHeaders, isLoggedIn, login, loginForm, logout, submitLogin } from "./auth";
export { trackConsoleErrors, type ConsoleTracker } from "./console";
export { LANGS, tr, type Lang } from "./i18n";
export { expectNoHorizontalScroll } from "./layout";
export { expectPrefsApplied, setPrefs, THEMES, type Prefs, type Theme } from "./prefs";
export { requirePasswordChange, reseed } from "./seed";
export { snap } from "./snap";
