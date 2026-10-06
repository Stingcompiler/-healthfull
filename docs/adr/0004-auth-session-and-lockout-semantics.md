# 0004: Sign-in, lockout and session semantics

Date: 2026-10-06. Status: accepted.

## Context
FEATURES 0.1 and 14.4 ask for username/password login, forced password change on first login and a
lockout after repeated failures, without fixing the edge cases. The Phase 0 backend, frontend and e2e
suite all depend on the exact behavior, so it is recorded here.

## Decision
Lockout (`backend/domain/lockout.py`, property-tested):
- Failures 1 to 5 each return `401 INVALID_CREDENTIALS`. The 5th failure also sets a 15-minute lock.
- From the 6th attempt, while the lock lasts, every attempt returns `423 ACCOUNT_LOCKED` with
  `details.locked_until` (ISO time) and `details.retry_after_seconds`, even with the right password.
  Attempts while locked do not extend the lock. When it expires the counter restarts from zero.
- Unknown usernames never lock and cost the same hashing time as a real check. There is no per-IP
  limit yet (an open item for Phase 8 hardening).
- A successful login resets the counter.

Session and CSRF:
- Django session cookie plus CSRF on every unsafe request, login included (login CSRF).
  `GET /api/auth/csrf` sets the `csrftoken` cookie.
- Login rotates `csrftoken`, so the SPA reads the cookie on every unsafe request instead of caching it
  (`frontend/src/lib/api/csrf.ts`).
- The session idles out after `Policy.session_idle_minutes` (default from `SESSION_IDLE_SECONDS`).
  Every request refreshes it.

Forced password change:
- A user with `must_change_password` gets `403 PASSWORD_CHANGE_REQUIRED` on every session endpoint
  except `/api/auth/{csrf,login,logout,me,me/preferences,change-password}` and `/api/ops/health`.
- The SPA route guard sends such a user to `/change-password`. Any API call that answers
  `PASSWORD_CHANGE_REQUIRED` mid-session makes the SPA refetch `/api/auth/me`, which triggers the same
  redirect (`frontend/src/lib/query.ts`).

Break-glass:
- A Django superuser holds every registered permission and bypasses the role matrix. Only the seeded
  `admin` account is a superuser by default. Every other user gets the union of their roles' defaults
  plus `RolePermission` overrides.

## Consequences
- The UI shows the locked message from the 6th attempt, not the 5th (`e2e/tests/auth.spec.ts`).
- Changing the attempt count or duration is a change to `domain/lockout.py` and its tests, plus this ADR.
