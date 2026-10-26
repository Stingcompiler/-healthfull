# 0026: An ended session keeps the page and its draft behind a sign-in dialog

Date: 2026-10-26. Status: accepted (inspection finding F06). Amends the frontend side of ADR 0004.

## Context
Any 401 set the cached user to null; `AuthGuard` then unmounted the page and sent the user to
`/login?redirect=...`. A doctor whose session expired while writing a note lost the note: the
form state lived only in the unmounted component, and the page's own leave guard went with it
(`docs/inspection/REPORT-2026-10.md`, F06).

## Decision
- A 401 under a signed-in user marks the session **expired** (`lib/auth/session.ts`, per query
  client) and keeps the cached user. A refused sign-in (`INVALID_CREDENTIALS`) is not an ended
  session. With nobody signed in, a 401 still means "go to /login".
- `AuthGuard` keeps the page mounted but hidden (`display: none`, `inert`, `aria-hidden`; the
  wrapper element is the same in every state, so React never remounts the page) and shows
  `ReauthDialog` (no close button, Escape and outside clicks ignored), the username prefilled.
- Same user signs in: the dialog closes, every query is fetched again, the draft is where it
  was; the user saves again.
- Another user signs in, or "Sign out": the page is unmounted first (state `switching`), then
  every cached query of the previous user is removed and the app starts over at `/` (or
  `/login`, `/change-password`). The draft is dropped without ever being shown.
- While expired, `/api/auth/me` answering 401 stays an error so the cached user is kept.

## Consequences
- A draft survives an expiry only in this browser tab's memory; a reload still loses it (no
  draft is written to storage, so nothing of a patient's record stays on a shared machine).
- While the dialog is open, the previous user's page is in the DOM, hidden. It is not shown on
  screen, and leaving the workstation still requires a password to see it again; "Sign out"
  discards it.
- Tests: `src/lib/query.test.ts`, `src/app/layouts/ReauthDialog.test.tsx` (dirty draft, 401,
  same user resumes, other user never sees it, wrong password keeps it), e2e
  `tests/followups/pre-trial.spec.ts` (`@pretrial`, the clinic NoteEditor).
