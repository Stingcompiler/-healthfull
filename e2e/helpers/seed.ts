import { execFileSync } from "node:child_process";

import { BACKEND_DIR, DB_NAME } from "../env";

function manage(args: readonly string[]): string {
  return execFileSync("uv", ["run", "python", "manage.py", ...args], {
    cwd: BACKEND_DIR,
    env: { ...process.env, DB_NAME, DJANGO_DEBUG: "1" },
    stdio: "pipe",
    timeout: 120_000,
    encoding: "utf8",
  });
}

/**
 * Re-runs `manage.py seed_e2e` against the e2e database. The command is
 * idempotent and resets the seed users (password, lockout, preferences,
 * must_change_password), so a spec that changes one calls this afterwards to
 * leave the data clean.
 */
export function reseed(): void {
  manage(["seed_e2e"]);
}

/**
 * Flags a seed user as having to change the password at the next sign-in, the
 * state an administrator's password reset leaves behind (there is no admin UI
 * for it before Phase 6). Undo with `reseed()`.
 */
export function requirePasswordChange(username: string): void {
  if (!/^[a-z][a-z0-9_]*$/.test(username)) throw new Error(`Not a seed username: ${username}`);
  const updated = manage([
    "shell",
    "-c",
    `from apps.core.models import User; print(User.objects.filter(username="${username}").update(must_change_password=True))`,
  ]).trim();
  if (updated !== "1") throw new Error(`Expected to flag 1 user "${username}", flagged ${updated}`);
}
