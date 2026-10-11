# 0019: A twelfth role, `display`, for the waiting-room kiosk

Date: 2026-10-10. Status: accepted.

## Context
FEATURES 0.2 lists eleven roles and ARCHITECTURE 4.10 repeats them. The waiting-room screen
(FEATURES 2.3, `/display/queue`) is a kiosk page outside the app shell, but it ran in the
signed-in session of a user holding `visits.view_queue`: in practice a receptionist's account
left signed in on a TV in the waiting room. That session can open every reception screen
(patient files, phones, the queue board), so anyone with a keyboard at the TV could too. The
wave a integration recorded this as a follow-up needing a core role change.

## Decision
- A twelfth role, `display` ("شاشة الانتظار" / "Waiting-room display"), seeded by core
  migration 0014 (the frozen list of migration 0002 is unchanged; `test_roles` reads both).
- A new permission `visits.view_display` guards the waiting-room feed
  (`GET /api/visits/queue/display`), held by `display` and by every role that held
  `visits.view_queue` before (receptionist, doctor, nurse, manager, admin), so their kiosk
  tabs keep working. The `display` role holds no other permission: a backend sweep over the
  whole OpenAPI contract proves every other permission-gated operation answers 403 to it.
- The feed now carries the active departments for the screen's clinic picker, so the kiosk
  needs no second endpoint (it read `/api/visits/options`, which needs `visits.view`).
- The SPA sends a user whose only permission is `visits.view_display` to `/display/queue`
  from any staff screen (UI convenience only; the server refuses the data anyway).
- Users get the role from the users screen like any other; the role's permissions are edited
  in the matrix like any other (the matrix may still widen it; the defaults are minimal).

## Consequences
- FEATURES 0.2 and ARCHITECTURE 4.10 list twelve roles; `display` is a device account, not a
  person, so it never appears as an approver or a performer.
- A kiosk account still has a password and the normal lockout and session rules (ADR 0004);
  its session times out like any other unless the center sets a longer timeout.
- e2e seeds a `display` user (`e2e/fixtures/users.ts`, `seed_e2e`).

## Code
`apps/core/roles.py`, `apps/core/migrations/0014_display_role.py`, `apps/visits/permissions.py`,
`apps/visits/api.py` (`get_display`), `apps/visits/services.py` (`waiting_room`),
`apps/core/tests/test_display_role.py`; frontend `app/guards.ts` (`isKioskOnly`),
`app/routes.ts`, `features/visits/pages/QueueDisplayPage.tsx`; e2e
`e2e/tests/followups/display-role.spec.ts`.
