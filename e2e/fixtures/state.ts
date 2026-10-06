import path from "node:path";

import { AUTH_DIR } from "../env";

/**
 * Session of the e2e admin (every permission), written by global-setup.ts.
 * Use with `test.use({ storageState: ADMIN_STATE })`.
 */
export const ADMIN_STATE = path.join(AUTH_DIR, "admin.json");

/** A browser with no session and no saved preferences. */
export const ANONYMOUS_STATE = { cookies: [], origins: [] };
