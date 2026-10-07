import path from "node:path";

import { AUTH_DIR } from "../env";

/**
 * Session of the e2e admin (the admin role: the UI shows it every module), written by
 * global-setup.ts. Use with `test.use({ storageState: ADMIN_STATE })`.
 */
export const ADMIN_STATE = path.join(AUTH_DIR, "admin.json");

/**
 * Session of the e2e pharmacist: a role with few modules, so the shell (phone tab bar,
 * sidebar) is also checked in its sparse form. Written by global-setup.ts.
 */
export const PHARMACIST_STATE = path.join(AUTH_DIR, "pharmacist.json");

/** A browser with no session and no saved preferences. */
export const ANONYMOUS_STATE = { cookies: [], origins: [] };
