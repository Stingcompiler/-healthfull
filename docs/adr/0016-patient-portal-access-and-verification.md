# 0016: Patient portal: sign-in with receipt codes, separate sessions, public receipt check

Date: 2026-10-10. Status: accepted.

## Context
FEATURES 15.1 asks for a QR on printed receipts that anyone can check, and 15.2 for a web portal
where patients see appointments, approved results and instructions. PROGRESS left both open:
lab results were not yet visible to patients and the receipt QR carried `number|amount|day`,
which only staff could check. Patients have no accounts; the clinic runs on a LAN; the portal
must never become a way into staff data or into another patient's file.

## Decisions

**Credentials.** A patient signs in with the file number, the phone on file and an access code
printed on a receipt. The cashier issues the code from the receipt screen
(`POST /api/portal/access-codes`, `portal.issue_access_code`, now also held by cashiers and
cashier supervisors). Codes are eight digits from `secrets`, stored only as a Django password
hash, shown once, valid 30 days (`PORTAL_CODE_TTL_DAYS`). Issuing a code revokes the file's
earlier codes and ends the sessions opened with them. "One-time" means the code is printed
once and can never be shown again; it may be used to sign in again until it expires, because
results are approved hours after the receipt is printed. A file without a phone gets no code
(`PORTAL_PHONE_REQUIRED`).

**Abuse control** (the staff rules of ADR 0005, for patients):
- Every refusal is `401 PORTAL_INVALID_CREDENTIALS`, whichever part was wrong, after exactly one
  password-hash computation (unknown file, wrong phone and wrong code cost the same; tested).
- A typed file number, known or not, locks after 5 failures for 15 minutes (`423 PORTAL_LOCKED`),
  state in `PortalThrottle` (scope `file`), so a lock never tells which file numbers exist.
- A code locks for good after 5 wrong codes given with the right file number and phone (a new
  receipt brings a new code). A wrong phone does not count against the code, so knowing a file
  number is not enough to lock its owner out.
- An address that fails 20 times in 15 minutes gets `429 RATE_LIMITED` before any hashing.
- Every sign-in, refusal, lock, code issue and sign-out is an append-only `PortalEvent`.

**Sessions.** Never the staff session. The portal cookie `hospital_portal` is HttpOnly,
SameSite=Strict, Secure when staff cookies are, and scoped to `path=/api/portal`, so it is not
even sent to staff endpoints; staff endpoints authenticate `request.user` only, and portal
endpoints only the portal cookie (`PortalAuth`), so neither opens the other (tested both ways,
also for a superuser). The token is 32 random bytes; only its SHA-256 is stored
(`PortalSession`). A session ends at sign-out, after 15 minutes idle
(`PORTAL_SESSION_IDLE_SECONDS`), 4 hours after sign-in (`PORTAL_SESSION_MAX_SECONDS`), or when its
code is revoked. The SPA also signs out after the idle time without input. Unsafe portal calls
pass the API-wide CSRF guard. `GET /api/portal/session` answers 200 with or without a session,
so the sign-in page asks without a failed request.

**Object-level access.** Every patient endpoint filters by the signed-in person's files
(`patients.person_file_ids`, so merges are followed); any other id is `404 NOT_FOUND`, never 403,
so the portal does not confirm that someone else's record exists. Tests cover every endpoint
across two patients.

**What patients see.** Approved results only: the current approved version, flagged
`amended` with a note when it corrects an earlier one; drafts and superseded versions never.
Invoices show the patient share per line, the patient due, paid and outstanding; never payer
shares, gross prices, discounts, coverage or claim states. Receipts show amount, method and a
public status; never the cashier. Prescriptions show dose, route, frequency, duration,
instructions and whether they were dispensed; clinical notes are not shown. Instructions are
the lab tests' preparation texts for tests still to be done.

**Booking.** Doctors with an active weekly schedule only; a slot must be one of the free slots
of that day, at least 60 minutes ahead and at most 30 days ahead; at most 3 upcoming bookings
per person and one per doctor per day (`domain.portal.check_booking`, Hypothesis-tested).
Cancellation of one's own booking until 2 hours before it starts, reason `PATIENT_REQUEST`.
The appointment columns that name a user (`created_by`, `cancelled_by`) name the inactive,
password-less, role-less user `portal-system`, and the audit context names the portal session.

**Public receipt check.** The receipt QR now opens `/verify/<token>?r=<number>`; the token is
20 base32 characters (100 bits) of HMAC-SHA256 over the receipt number with the server's
`SECRET_KEY`, so only the server can make one. `GET /api/portal/verify` answers the center
name, number, day, amount, status and the payer's initials (at most two letters); an unknown
number and a wrong token both answer 404. Every check counts against the address (60 per 10
minutes, then 429). Status is `valid`, `void` (rejected transfer, reversed payment or reversal
row) or `pending` (a transfer the bank has not confirmed): a pending transfer is not reported as
plainly valid. The printed text under the QR stays `number|amount|day` for the staff check,
which now also reads the new QR URL.

## Consequences
- Rotating `SECRET_KEY` invalidates the QR of every printed receipt (the staff check by number
  still works). Keep the key stable across updates.
- A patient whose phone changed needs reception to update the file before a code helps.
- The portal has no self-service code request; a lost receipt means asking the cashier for a
  new code, which also ends the old code's sessions.
- Settings: `PORTAL_CODE_TTL_DAYS`, `PORTAL_CODE_MAX_ATTEMPTS`, `PORTAL_SESSION_IDLE_SECONDS`,
  `PORTAL_SESSION_MAX_SECONDS`, `PORTAL_FILE_MAX_FAILURES`, `PORTAL_FILE_LOCK_SECONDS`,
  `PORTAL_LOGIN_IP_MAX_FAILURES`, `PORTAL_LOGIN_IP_WINDOW_SECONDS`, `PORTAL_VERIFY_IP_MAX`,
  `PORTAL_VERIFY_IP_WINDOW_SECONDS`, `PORTAL_BOOKING_LEAD_MINUTES`,
  `PORTAL_BOOKING_HORIZON_DAYS`, `PORTAL_MAX_OPEN_APPOINTMENTS`, `PORTAL_CANCEL_CUTOFF_HOURS`
  (read with defaults in `apps/portal/conf.py`).
- `manage.py maintenance` ends idle portal sessions (rows stay as the sign-in record) and
  removes stale portal counters.

## Code
`domain/portal.py`, `apps/portal/{models,conf,services,queries,security,schemas,api}.py`,
`apps/portal/e2e_fixtures.py`, tests in `apps/portal/tests/` and `domain/tests/test_portal.py`;
frontend `src/portal/`; e2e `e2e/tests/portal/`, `e2e/module-routes/portal.ts`.
