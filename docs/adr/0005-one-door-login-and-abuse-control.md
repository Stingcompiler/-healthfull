# 0005: One credential check for every login path, abuse control, unset preferences

Date: 2026-10-07. Status: accepted. Amends 0004 (lockout scope, break-glass account).

## Context
The Phase 0 review found that the Django admin login (`/admin/login/`, proxied by Caddy) skipped
every control of the API login: lockout, audit, forced password change, session idle policy. It
also found a user-enumeration oracle (unknown usernames never locked, existing ones answered 423),
no limit on password spraying, a brute-force path through change-password, and a server profile
that always overrode the device's theme and language.

## Decision
One door:
- `apps.core.services.authenticate_credentials` is the only credential check. The API login, the
  admin login form (`apps.core.admin_site`) and the only authentication backend
  (`apps.core.auth_backends.LockoutBackend`, so any `authenticate()` call) go through it.
- Login and logout audit rows and the `Policy.session_idle_minutes` expiry come from the
  `user_logged_in` / `user_logged_out` signal receivers, for every path.
- The admin site refuses users with `must_change_password`, at login and for an existing session.
- Lock fields are read-only in the admin; an administrator unlocks through an action that asks for a
  reason and writes an `ACCOUNT_UNLOCKED` audit row with the actor (invariant 4).

Abuse control (replaces 0004's "unknown usernames never lock" and "no per-IP limit"):
- Unknown usernames follow the same lockout state machine as accounts (`LoginThrottle`,
  scope `username`): 401 for failures 1-5, then 423 for 15 minutes. Answers cannot reveal which
  usernames exist.
- Wrong passwords of inactive accounts count like any other; the right password of an inactive
  account is refused without counting.
- Per client address (`LoginThrottle`, scope `ip`, `domain/throttle.py`): after
  `LOGIN_IP_MAX_FAILURES` (30) failed logins within `LOGIN_IP_WINDOW_SECONDS` (900), logins from
  that address answer `429 RATE_LIMITED` with `details.retry_after_seconds`, before any password
  hashing. Successful logins do not use the budget.
- Wrong current passwords on `change-password` count toward the account lockout; the one that locks
  the account also ends the session (`423 ACCOUNT_LOCKED`). While locked, change-password is refused
  without checking the password.
- `manage.py maintenance` (daily, compose service `maintenance`) removes stale throttle rows and
  expired sessions.

Break-glass (replaces 0004's paragraph):
- `seed_e2e` creates `admin` as a normal user with the admin role and a separate superuser `root`.
  `seed_e2e` only runs with DEBUG on against an `e2e_*` / `test_*` database, or with
  `ALLOW_SEED_E2E=1` (which `make seed` sets for the dev database).

Preferences:
- `User.language` / `User.theme` may be unset (`MeOut` sends `null`): the user never chose. The SPA
  then keeps the device's explicit choice (e.g. the language picked on the login page) and saves it
  to the profile once; with no local choice the theme follows `prefers-color-scheme` and nothing is
  saved (ARCHITECTURE 5.1).

## Consequences
- `MeOut.language` and `MeOut.theme` are nullable in the OpenAPI contract.
- e2e uses the `admin` role user for the responsive matrix (the UI shows the admin role every
  module); `root` exists only for superuser checks.
- Changing the address limit is a settings change (`.env`); changing the lockout rules is still a
  change to `domain/lockout.py`, its tests, 0004 and this ADR.
