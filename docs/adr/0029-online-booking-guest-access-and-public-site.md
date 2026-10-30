# 0029: Online booking for patients and guests, approval by reception, and the public website

Date: 2026-10-29. Status: accepted (Phase 0 of `docs/PUBLIC-SITE-PLAN.md`, decided by the owner
on 2026-10-29). Extends 0016 (portal) and 0023 (center page) without weakening their rules; related: 0005
(abuse control), 0028 (how the public reaches a center), 0021 (notifications).

Markers: **[SETTLED]** is the owner's decision (plan section 7 and the Phase 0 brief, binding).
**[DECIDED 2026-10-29]** is a Phase 0 recommendation the owner reviewed and accepted on
2026-10-29 (section K lists those decisions). Anything unmarked follows from those. Every number
below is a default, editable by the administrator in the settings row.

## Context
`main` already has a public center page, a patient portal with doctor-day-slot booking for
patients who have a file, staff appointments, and appointments for callers without a file
(`contact_name`, `contact_phone`, `patient = NULL`, used only by staff). It has no approval step, no
guest access, no reschedule by the patient, no doctor time off, no administrator-editable booking
rules (they are environment settings, `apps/portal/conf.py`), and no way to tell the patient
anything except in the page (no SMS, no e-mail). `docs/inspection/public-site-impact.md` holds the
evidence with file and line citations.

## Decisions

### A. What is settled [SETTLED]
1. **Switches.** `site_enabled` and `online_booking_enabled` (and `patient_tracking_enabled`) are
   administrator switches, default off, enforced in services and routers (0028 decision 1).
2. **Approval.** `require_approval` defaults **on** for a new install. An online booking, **by a
   signed-in patient or a guest**, enters `requested` and becomes `booked` only when reception
   approves. An existing install is seeded **off** (section K, decision 1).
3. **Both registered-patient booking and guest booking ship in V1.** Guests need no file. Cap: 2
   open guest bookings per phone (`max_guest_bookings_per_phone`, editable). No automatic phone
   blocking for no-shows in V1.
4. **No queue priority** for online bookings; the same queue as walk-ins.
5. **No fees on the site.** The page says fees are paid at reception and shows the cancellation
   policy text.
6. **Testimonials:** staff-entered and manager-approved only (`core.approve_testimonial`); never
   submitted by the public.
7. **Reschedule by the patient:** allowed, the same cut-off as cancellation, for signed-in
   patients and guests.
8. **Request expiry rule.** A `requested` booking expires `request_ttl_hours` (default **24**,
   editable) after creation, **capped at `starts_at` minus the booking lead time**:
   `expires_at = min(created_at + request_ttl_hours, starts_at - lead_minutes)`. This replaces the
   two contradictory wordings in plan D3 and section 7.8 (one said "never later than lead time",
   the other "24 hours before the slot").
9. **Reception inbox WhatsApp button.** Each inbox row has a click-to-chat button, a plain
   `https://wa.me/<digits>?text=<prefilled status message>` link built from the booker's phone
   with `domain.center_page.whatsapp_number` (Sudanese local numbers fold to 249). No API, no
   server-side sending, nothing recorded as "sent" because the system cannot know. The message
   carries the center name, doctor, date and time, status and the booking reference; **never the
   PIN**.

### B. Settings, switches and permissions
- A singleton `core.PublicSiteSettings` (pghistory-tracked, with reason) holds the three switches
  and the booking rules moved from the environment: `lead_minutes`, `horizon_days`, `max_open`,
  `cancel_cutoff_hours`, `reschedule_allowed`, `reschedule_cutoff_hours`, `require_approval`,
  `request_ttl_hours`, `guest_booking_enabled`, `max_guest_bookings_per_phone`, and the abuse
  limits of section F. The old environment values become the migration's defaults, then `conf.py`
  keeps only abuse-control settings. Behavior when a switch is off is the table of plan D4.
- **Permissions.** New codes: `core.manage_public_site` (website content and the switches),
  `visits.manage_online_bookings` (the inbox: approve, reject, link patient, reissue PIN, cancel on
  behalf), `core.approve_testimonial`. The center page and its notices are guarded today by
  `core.manage_settings` (`backend/apps/core/api.py` lines 410-470); they move to
  `core.manage_public_site`, while `core.manage_settings` keeps the center profile and policy.
- **[DECIDED 2026-10-29] Permission migration keeps every grant.** A data migration
  gives `core.manage_public_site` to **every role that holds `core.manage_settings`**, computed as
  the *effective* grant (default roles `admin` and `manager`, with `RolePermission` overrides
  applied), so a role the administrator had granted the old code (for example a receptionist) keeps
  editing the center page, and a role that was denied it does not gain the new one by default.
  Rows are written only where they differ from the new code's default (the matrix deletes
  override rows that equal the default, `test_matrix_toggle_changes_effective_permissions`). The
  migration is idempotent and has a test per case (default, granted extra role, denied default
  role, no override rows).
- **Doctor eligibility.** A doctor is offered online only when `active` and the new flag
  `online_bookable` (default false), so going live exposes nobody by accident.

### C. Availability and double-booking
- Availability = active `DoctorSchedule` rows in range, minus appointments in `booked` or
  `requested`, minus `DoctorTimeOff` ranges. A `requested` booking holds its slot (otherwise
  approval means nothing).
- The per-doctor row lock and `_check_slot` stay as the first guard. A database backstop is added:
  `EXCLUDE USING gist (doctor_id WITH =, tstzrange(starts_at, ends_at) WITH &&) WHERE (status IN
  ('booked','requested'))` (needs `btree_gist`; migration in `visits`). The range is half-open, so
  back-to-back slots do not conflict, matching `starts_at < end AND ends_at > start` in
  `_check_slot`. An exclusion violation is a Postgres `IntegrityError` (SQLSTATE 23P01), **not** a
  trigger message, so it does not go through `DB_GUARD_CODES` (which is checked against
  `pg_proc`); the booking service catches the violation and raises `APPOINTMENT_CONFLICT`, and the
  generic `IntegrityError` handler (`409 CONFLICT`) stays as the last resort.
- **[DECIDED 2026-10-29] The constraint migration pre-checks live data.** Before
  adding the constraint the migration queries for overlapping `booked` rows per doctor and, if any
  exist, **fails with a message that lists them** (doctor, both appointment ids, both times)
  instead of Postgres's bare constraint error, and changes nothing. The administrator resolves
  them (cancel or reschedule through the app) and re-runs. The finding in
  `public-site-impact.md` is that the application cannot produce such rows today, so the check is
  expected to pass; it exists for data that did not come through the service.
- **Lazy expiry.** The `maintenance` loop is hourly (`infra/docker-compose.yml`), so it cannot be
  the only thing that frees an expired request's slot. The booking service expires stale
  `requested` rows of that doctor, under the doctor lock, before it checks the slot, and the slot
  queries ignore a request whose `expires_at` has passed; `maintenance` then only tidies and
  notifies. Approval of an expired request is refused (`ONLINE_REQUEST_EXPIRED`) whether or not
  the sweep has run.
- **Minimum review window.** A booking is refused when `expires_at - now` would be under 30
  minutes (`min_review_minutes`, default 30, editable), so a request cannot be created already expired (`starts_at - lead` is at
  least "now" by the lead rule, so a slot just past the lead time would otherwise have a zero
  window).
- Idempotency: public booking POSTs require an `Idempotency-Key` (UUID); same key and same body
  returns the stored answer, same key and a different body is `409 IDEMPOTENCY_MISMATCH`; rows
  expire after 24 h.

- **[DECIDED 2026-10-29, owner] No overbooking, ever.** The doctor/time exclusion constraint
  is absolute: there is no override flag, parameter or role, for staff or anyone. An urgent
  patient is seen through the existing walk-in path (a visit and the queue), which takes no
  appointment slot. This closes open item 1 of `docs/inspection/public-site-impact.md`.

**Phase 3 as built (2026-10-29).**
- `AppointmentStatus.REQUESTED`, `Appointment.source` (`staff|portal|guest`), `expires_at`,
  `approved_by/approved_at` (both or neither, a check), a check that a request has an expiry,
  `btree_gist` and `visits_appointment_no_overlap` land in one migration
  (`visits/0005`), whose `verify_no_overlaps` step stops with the list of overlapping pairs
  (doctor, both ids, both times) and changes nothing. The state machine and expiry rules are
  `domain.appointments` (Hypothesis-tested edge by edge); availability is
  `domain.availability.free_slots` (Hypothesis over schedules x time off x bookings).
- Every booking takes the doctor's row lock, expires that doctor's due requests (system actor,
  reason `ONLINE_REQUEST_EXPIRED`), checks the slot, and inserts inside a savepoint; an exclusion
  violation (`violated_constraint`, SQLSTATE 23P01) is answered `APPOINTMENT_CONFLICT`. The
  hourly `maintenance` run sweeps the rest (`visits.expire_requests`). The system actor is the
  portal's inactive system user (`portal-system`), the user online requests are created by.
- While approval is on, the portal offers only slots at least `lead + min_review_minutes`
  ahead (`domain.public_site.offered_booking_rules`) and still refuses a request whose review
  window would be short (`ONLINE_REVIEW_WINDOW_TOO_SHORT`, also when `request_ttl_hours` is
  shorter than the window).
- Minimal staff endpoints so requests are never stuck before the Phase 4 inbox:
  `POST /api/visits/online-bookings/{id}/approve` and `/reject` (`visits.manage_online_bookings`,
  default receptionist, manager, administrator; reject carries a reason code of
  `appointment_cancel`, default `ONLINE_REJECTED`, a note, actor and time). The doctor's day
  view shows requests with Approve and Decline. `ONLINE_REQUEST_EXPIRED` is never offered in a
  staff reason list.
- **Reschedule by a signed-in patient** (`POST /api/portal/appointments/{id}/reschedule`):
  only a confirmed (`booked`) booking moves (a request is cancelled and booked again); the new
  slot is validated like a booking (open count and same-day rule exclude the moved one), and the
  new booking follows `require_approval` like any online booking (it waits for reception when
  approval is on, so the old slot is released at once). Lock order: person, both doctors by id,
  then the appointment; staff reschedule now takes the doctor lock before the appointment too.
- `DoctorTimeOff` (doctor, starts/ends, reason ar/en, at least one; created_by; history;
  `visits_time_off_no_overlap`). Adding a period never cancels bookings inside it: they are
  returned so reception moves or cancels them with the patient. Staff booking inside time off
  is refused (`DOCTOR_TIME_OFF`). Endpoints and the screen (a "Time off" action on the doctors'
  schedule list at `/administration/departments`) use `core.manage_departments`, the
  permission of the schedule editor on that page (`visits.manage_schedules` stays unused).
- **`online_bookable` on existing installs.** `visits/0005` sets it true for every doctor who
  can be booked on the portal today (active, active user, active weekly schedule) **only when
  online booking is already on** in the settings row (which ADR K1 seeds on for an existing
  install); otherwise (a new install, or booking off) nobody is offered until the administrator
  ticks the doctor in the center page's doctor profile ("Offered for online booking",
  `core.manage_public_site`). Registered patients of a center that books online today are not
  cut off, consistent with K1.
- The reason codes `ONLINE_REJECTED` and `ONLINE_REQUEST_EXPIRED` are seeded (`core/0022`).
  The plan's `PATIENT_RESCHEDULE` was not added: a reschedule is the `rescheduled` state and
  the link, not a cancellation, so it needs no cancel reason.
- The portal shows the patient-facing status (`display_status`, `domain.portal_status`,
  booking family): awaiting approval, confirmed, you were received, moved, cancelled by you,
  cancelled by the center, declined, request expired, missed.
- `PortalEvent.kind` and `PortalThrottle.scope` were **not** widened: Phase 3 writes no new
  event kind or throttle scope; the widening ships with the guest kinds in Phase 4.

### D. Identity of a guest
A guest booking is an `Appointment` with `contact_name`, `contact_phone`, `patient = NULL`,
`source = guest`. The confirmation screen shows a **booking reference (10 base32 characters)** and
a **6-digit PIN once**; the PIN is stored only as a password hash. Reference plus PIN opens a view
limited to that one booking (status, time, doctor, cancel, reschedule, within the rules). It never
opens a patient file, and the guest cookie (`hospital_guest`, path `/api/portal/guest`) never
reaches staff or patient endpoints, nor the reverse (three-way matrix test). Sign-in follows
0016: uniform `401 GUEST_INVALID_CREDENTIALS`, one hash computation per attempt, lock after 5
failures per reference, per-address 429, every event in `PortalEvent`. The phone is **unverified**
(no SMS): reception verifies identity at arrival and links the booking to a file explicitly
(`link-patient`, audited, refuses when a different file is already linked; no automatic match by
name or phone, as FLOW step 1). `convert_appointment` is unchanged.
The reschedule of a guest booking creates a new appointment (the old becomes `rescheduled`,
linked); the guest access therefore belongs to the booking **chain**, not to one appointment row:
`GuestBookingAccess` points to the current appointment and is moved in the same transaction.

**Phase 4a as built (2026-10-30, backend only; the screens are Phase 4b).**
- **Public reads.** `GET /api/portal/doctors`, `/doctors/{id}/days`, `/doctors/{id}/slots` keep
  their paths but need no session (patients and guests read the same answers: free times only,
  never who holds the others), answer `ONLINE_BOOKING_DISABLED` while booking is off, and count
  against the per-address public page limit. They no longer answer `PORTAL_DISABLED`.
- **Guest booking.** `GET /api/portal/challenge`, then `POST /api/portal/guest-bookings` with
  the `Idempotency-Key` header (`apps/portal/guest.py`). Order of checks: switches
  (`online_booking_enabled`, then `guest_booking_enabled`, `GUEST_BOOKING_DISABLED`), the key
  (`400 IDEMPOTENCY_KEY_REQUIRED` without a UUID), the stored answer (`replayed`), the address's
  daily limit (429), name and phone, the proof-of-work (spent in its own committed step, so a
  refused booking still uses it: `POW_INVALID`, `POW_EXPIRED`, `POW_ALREADY_USED`), then under
  the phone's lock (a `PortalThrottle` row of scope `guest_phone`) and the doctor's lock the
  slot rules of a portal booking, one booking per phone per doctor per day
  (`PORTAL_ALREADY_BOOKED`), `GUEST_PHONE_LIMIT` and `ONLINE_DOCTOR_DAY_FULL`. Only a created
  booking is stored for replay; a refusal is evaluated again on retry.
- **Deviation: the replayed PIN.** Section D stores the PIN only as a password hash. A retry
  after a lost answer must show the PIN again or the guest loses the booking, so the stored
  answer (`portal.IdempotentRequest`, at most 24 hours) keeps the PIN **sealed**: XOR with an
  HMAC of the server secret and the client's key, and only the SHA-256 of the key is stored, so
  neither a database copy nor the secret alone opens it. Once staff issue a new PIN, or the
  booking is purged, the replay answers `pin: null`.
- **Caps apply to guests.** The per-doctor-day request cap and the per-address daily cap count
  guest bookings only; a signed-in patient is already limited by `max_open` and is known.
  The proof-of-work gets two more bits once an address is one request short of its daily limit.
- **Guest sign-in and session.** `POST /api/portal/guest-bookings/sign-in` sets
  `hospital_guest` (path `/api/portal/guest`, HttpOnly, SameSite=Strict; idle 15 minutes, at
  most 2 hours, `GUEST_SESSION_*` settings). Every refusal is `401 GUEST_INVALID_CREDENTIALS`
  after one hash; the fifth wrong PIN locks the booking **until staff issue a new PIN** (not a
  timed lock: the reference is 50 random bits, so the only target is a known reference); 20
  failures per address in 15 minutes answer 429. A new PIN ends the guest's open sessions.
  Guest view, cancel and sign-in need online booking on; reschedule also needs guest booking.
  `POST /api/portal/guest/sign-out` is idempotent. CSRF: the existing `GET /api/auth/csrf`
  (no new endpoint was needed, ADR 0028 decision 3).
- **Chain.** `portal.GuestBookingAccess.appointment` (one to one) is moved to the new row in the
  reschedule transaction; reissuing a PIN on an earlier row answers `NOT_A_GUEST_BOOKING`.
- **Inbox** (`apps/portal/inbox.py`, router `/api/visits/online-bookings*`,
  `visits.manage_online_bookings`): list (`status`, `day`, `doctor_id`), approve and reject
  (now answering the inbox row and refusing a staff booking with 404), cancel on behalf,
  `reject-phone` (every open guest request of the phone key, one reason and note, the phone
  not blocked), `link-patient` (explicit; a merged file links to its survivor; another file
  already linked is `APPOINTMENT_PATIENT_MISMATCH`; only an open booking), `reissue-pin`
  (reason required, PIN shown once, audited in history and `PortalEvent`). Each row carries
  `reference`, `guest_locked`, `display_status`, `phone_open_requests` and `whatsapp_url`
  (`domain.guest_booking.status_message`: center, doctor, local date and time, status,
  reference; never a PIN). A patient's booking uses the phone on their file.
- **Notifications.** `online_booking_requested` (a request by a guest or a patient) and
  `online_booking_cancelled_by_patient` (a guest or patient cancels online) go to
  receptionists and link to `/appointments` (the day view approves and declines) until Phase 4b
  adds the inbox screen.
- **Audit and retention.** `PortalEvent.kind` and `PortalThrottle.scope` widened to 30
  characters (`portal/0006`; ALTER was not blocked by the append-only trigger). New kinds:
  `guest_booking_created`, `guest_view`, `guest_view_refused`, `guest_locked`,
  `guest_throttled`, `guest_logout`, `guest_cancelled`, `guest_pin_reissued`, `guest_purged`,
  `booking_rescheduled` (guests and patients), `booking_throttled`. The hourly maintenance ends
  idle guest sessions, deletes stored answers after 24 hours and spent challenges after their
  expiry, and anonymizes unlinked guest bookings cancelled (or expired) more than
  `guest_retention_days` ago **with the earlier rows of their reschedule chain** (they carry
  the same name and phone), deleting their guest access; `no_show` rows are not purged (the
  ADR names cancelled and expired only).

**Phase 4b as built (2026-10-30, the screens).**
- **`/portal/book`** (public; open while `online_booking_enabled` and `guest_booking_enabled` are
  on, a signed-in patient is sent to the booking of their file): doctor, day and time (the same
  `SlotChooser` as the patient booking), name and phone, then a review with "fees are paid at
  reception" and the center's cancellation policy, then the confirmation: reference and PIN shown
  once under a "save these now" card, a `wa.me` share of `share_url` (reference only) and print.
  The page links "already a patient? sign in" (while patient sign-in is on) and "open my booking".
- **Idempotency in the browser.** One attempt = one `Idempotency-Key` (UUID from
  `crypto.randomUUID`, or `getRandomValues` on plain HTTP) kept in `sessionStorage` with the
  details **and the solved challenge and nonce**, because the server's request hash covers them:
  a retry after a lost answer (timeout, dropped connection, reload: the page offers "send it
  again") resends the identical body and gets the stored booking. Any 4xx answer ends the attempt
  (its challenge is spent); changed details start a new one (`src/portal/guest/attempt.ts`).
- **Proof-of-work in the browser.** `GET /api/portal/challenge`, then a Web Worker searches the
  nonce with a bundled pure-JS SHA-256 (`src/portal/guest/{sha256,pow,solver}.ts`; no
  `crypto.subtle`, no CDN), counting up from 0 like `domain.proof_of_work.solve` (vitest checks
  the same nonces on fixed vectors); progress shows as text and a bar, the page stays usable; a
  browser without workers searches in yielding slices on the main thread.
- **`/portal/booking`**: reference and PIN sign-in (one message for every refusal, with the hint
  that a locked booking needs a new PIN from reception), then the booking: patient-facing status,
  time, doctor, name, masked phone, cancel and change of time within `can_cancel` /
  `can_reschedule`, sign-out. The page asks for the booking only after a sign-in from this tab
  (no 401 probe for a stranger).
- **Calls to book.** `GET /api/ops/site` gains `guest_booking` (true only while online booking
  is on too). The center page's hero leads with "Book online" when booking is open to the visitor
  (guest) or the patient (signed in), with sign-in beside it; the quick action and the phone's
  sticky bar follow; with guest booking off a visitor's quick action still leads to sign-in. The
  "online services are off" page and the patient sign-in link to `/portal/book` while guest
  booking is on.
- **Reception inbox** `/visits/online-bookings` (nav entry under the front desk,
  `visits.manage_online_bookings`): filters status, day, doctor; cards with the staff status,
  what the booker sees, source, phone, reference, the locked badge and the phone's open requests;
  approve, decline (reason code and note), cancel on behalf, decline every request of the phone
  (confirmed, one reason), link to a file (patient search; the server's refusal shown), issue a
  new PIN (reason; the PIN shown once in its own dialog), WhatsApp (`whatsapp_url`) and check-in
  (the existing dialog, `visits.create`). Refreshes every 30 seconds. The two staff notification
  kinds now open the inbox.
- **`/administration/public-site`** gains the guest switch and the limits per phone, per doctor
  and day, per address and day, the form-check bits and the retention days.
- **Deviations.** The PIN field is a plain numeric text input (the form kit has no password
  field; the PIN is a one-time code read from the confirmation). The e2e seed lowers the form
  check to 14 bits and raises the per-address daily cap (every spec books from 127.0.0.1); the
  product defaults are unchanged.

### E. State machine
`requested -> booked | cancelled(rejected, expired, cancelled by the booker, cancelled on behalf)`;
`booked -> arrived | rescheduled | cancelled | no_show`; every other edge is refused (tested edge
by edge). Reject and cancel carry a reason code in category `appointment_cancel`, a note, the actor
and the time (invariant 4); expiry is the system actor with reason `ONLINE_REQUEST_EXPIRED`.
`REQUESTED` is added to `AppointmentStatus` in the same migration as the exclusion constraint
(the constraint names the value). A booking creates **no** patient, visit, service line, invoice
or payment (asserted by row counts), so the seven invariants are untouched.

### F. [DECIDED 2026-10-29] Abuse limits for guest booking
Guests are anonymous and the phone is unverified, so the per-phone cap alone is spoofable (change a
digit). Added limits, all editable in the settings row, with the defaults the owner accepted:
- **Pending requests per doctor per day:** at most 10 (`max_pending_per_doctor_day`) `requested` rows for one doctor on one
  day; further attempts are refused with `ONLINE_DOCTOR_DAY_FULL`, so a flood cannot lock a whole
  day out of real patients.
- **Requests per client address per day:** at most 5 (`max_requests_per_address_day`; the address is `client_ip`, which needs the
  proxy configuration of 0028 decision 6), on top of the existing per-address 429 limits.
- **Bulk "reject all from this phone".** An inbox action that rejects every open request with the
  same normalized phone in one audited operation (one reason code, one note, the actor, the time on
  each row). It does not block the phone; automatic blocking stays out of V1 as decided.
- **Offline proof-of-work instead of a CAPTCHA.** The booking form asks `GET /api/portal/challenge`
  (a signed, expiring, single-use challenge) and the browser finds a nonce so that
  `SHA-256(challenge + nonce)` has N leading zero bits (`pow_difficulty_bits`, default 18, adjustable, raised for an
  address that is near its caps); the POST carries challenge and nonce and the server verifies in
  constant time. No third-party service, so it works on a LAN and offline. Two honest limits: it
  slows scripted floods, it does not stop a determined attacker (the caps, reception review and
  expiry are the real defense); and `crypto.subtle` exists only in secure contexts, while a LAN
  install may serve plain HTTP, so the hash runs in a bundled pure-JavaScript SHA-256 in a worker.

### G. [DECIDED 2026-10-29] Staff actions and retention
- **Reissue guest PIN** (inbox, reason required, audited): the old PIN stops working, a new one is
  shown once to the staff member, who reads it to the guest.
- **Cancel on behalf** of a booker (reason code and note), the same service as any cancellation.
- **Retention.** `guest_retention_days` (default 90, editable): the hourly `maintenance` anonymizes
  guest bookings that were never linked to a file and ended `cancelled` or `expired` more than that
  long ago (`contact_name` replaced by a fixed placeholder so the has-person check still holds,
  `contact_phone` and `notes` cleared, `GuestBookingAccess` deleted), and writes one `PortalEvent`
  with counts only. **Limit, stated plainly:** the appointment history table
  (`visits_appointmentevent`) is append-only by trigger (ARCHITECTURE 4.9), so the earlier copies
  of the name and phone in that history are not erased. **The owner accepted this on 2026-10-29**
  (section K, decision 3): audit integrity wins over erasing the earlier copies. The alternatives
  (exclude the contact fields from tracking for guest rows, or lift the trigger for this one purge)
  are not built. The administrator guide states that guest names and phones remain in the
  appointment history after the purge.
- **The confirmation screen shares the reference** with a `wa.me` link
  (`https://wa.me/?text=<message with the reference>`) so the guest can send it to themselves or
  family. The message contains the reference and the center's page address, **never the PIN**.

### H. Public website content
Fixed sections, not a CMS (0023 kept): hero, about, facilities, reasons, departments with service
names (no prices), doctors with qualifications, photo and clinic days, hours, insurance providers,
FAQ, testimonials, accessibility note, contact, address and a plain maps link, footer with the
policies. Images are uploaded `CenterMedia` rows (at most 2 MB), never external URLs. Hidden or empty
sections render nothing. The public answer keeps its pinned field set (a test) and still carries no
prices, no registration or tax numbers and no staff beyond the doctors shown. A new
`GET /api/portal/center-identity` (name and logo only) serves the staff sign-in even when
`site_enabled` is off.

**Phase 2 as built (2026-10-29).** `CenterPage` gained the hero, facilities (at most 20 rows),
reasons (at most 8), accessibility, privacy and cancellation policy texts, `maps_url` (a plain
`https://` link, `domain.center_content.maps_link`) and the switches `show_services`,
`show_insurance`, `show_faq`, `show_testimonials`, `show_facilities`, `show_policies`. Reasons and
accessibility have no switch: an empty value hides them. `CenterMedia` images are PNG, JPEG or
WebP judged by their bytes (`domain.images` walks the PNG chunks with their CRCs, the JPEG segments
and the WebP RIFF header; no imaging library was added), at most 2 MB and 8000 pixels a side, at
most 100 kept. `GET /api/portal/center-media/{id}` answers only while the website is on, only for
an active image, and a doctor photo only while that doctor is on the page; it counts against the
same per-address limit as the page. `core.approve_testimonial` defaults to the manager **and the
administrator** (the permission sweep requires the administrator to hold every code); editing a
testimonial's words or author withdraws its approval. Service names appear under their departments
only (a service without a department is not listed); the administration lists consultation, lab and
procedure services (drugs, consumables and beds are not offered). Gallery images follow
`show_about`; the hero image always shows when one is active. Layout: D-0021.

### I. Patient channel
No SMS or e-mail in V1. The patient is told in the page and in a portal inbox
(`portal.PatientNotice`, written in the same transaction as the event through one
`patients.notify` service with a `channels` list; SMS is a future channel behind the same call).
Staff get in-app notifications `online_booking_requested` and
`online_booking_cancelled_by_patient` (kinds table, `core/notification_kinds.py`). Guests have no
inbox: they have the reference and the WhatsApp message reception may send.

### J. Out of scope for V1
Branches; online payment and fee display; service-level booking (lab, procedures: V1 books doctor
consultation slots only); SMS and e-mail; map embeds; automatic blocking by no-show.

### K. Owner decisions of 2026-10-29 (binding)
1. **`require_approval` on a new install versus an existing one.** The Phase 1 data migration that
   creates the `PublicSiteSettings` row seeds `require_approval = true` on a **new install** and
   `require_approval = false` on an **existing install**, so registered patients of a center that
   already uses portal booking keep booking instantly until the administrator turns approval on.
   **Detection:** the migration counts the rows of `patients.Patient` (table `patients_patient`)
   at the moment it runs. One or more rows = existing install (a center that has registered at
   least one patient already has data); zero rows = new install. The migration depends on the
   latest `patients` migration, so the table always exists when it counts. A fresh install runs
   every migration on an empty database before any seed command (`seed_demo`, `seed_e2e`,
   `createsuperuser`), so it always sees zero patients and gets `true`. The migration runs once:
   later changes of the patient count do not touch the row; only the administrator does.
   **Phase 1 implementation note (2026-10-29):** the same detection seeds the switches, because an
   existing install already runs the patient portal and its booking (ADR 0016) and "registered
   patients keep booking instantly" needs both on: an existing install is seeded with
   `online_booking_enabled` and `patient_tracking_enabled` **on** and `site_enabled` **off** (so
   `/` does not change until an administrator switches the website on, ADR 0028 decision 4; the
   center page at `/portal` is hidden until then). A new install has all three off (0028
   decision 1). Code: `domain.public_site.initial_values`, migration `core/0020_public_site_seed`.
2. **Topology** (ADR 0028 decision 3): website, booking, portal and staff app on one name and one
   host; no public listener; security from the switches, authentication separation and throttles.
3. **Guest data in the append-only appointment history** after the retention purge: accepted and
   documented (section G).
4. **Defaults accepted**, every one editable by the administrator in the settings row:
   `max_pending_per_doctor_day` 10, `max_requests_per_address_day` 5, `pow_difficulty_bits` 18,
   `guest_retention_days` 90, `min_review_minutes` 30.

## Consequences
- Existing portal booking keeps its behavior on upgrade: an existing install is seeded with
  `require_approval = false` (K1), so signed-in patients still book instantly until the
  administrator turns approval on in `/administration/public-site`. A new install starts with
  approval on. The release notes say both.
- New or changed tests are listed per phase in `docs/inspection/public-site-impact.md`.
- Limitations for handover: no SMS/e-mail; guest phone unverified until arrival; consultation slots
  only; the site is down when the center's internet is down (fallback page only); no online payment.
- Widening needed in existing columns: `PortalEvent.kind` (max length 20) cannot hold
  `guest_booking_created` (21) and `PortalThrottle.scope` (10) cannot hold `guest_phone` (11);
  Phase 4 widens them in a migration (no trigger forbids ALTER on those tables).

## Code (planned)
`backend/domain/{portal,portal_status,booking_requests}.py`, `backend/apps/core/{models,services,api,schemas}.py`
(`PublicSiteSettings`, `CenterMedia`, `CenterFaq`, `Testimonial`), `backend/apps/visits/{models,services,api}.py`
(`REQUESTED`, `DoctorTimeOff`, exclusion constraint, inbox), `backend/apps/portal/{models,services,queries,api,security}.py`
(`GuestBookingAccess`, `IdempotentRequest`, `PatientNotice`), frontend `src/portal/`,
`src/features/visits/` (inbox), `src/features/admin/` (public site screens).
