# 0029: Online booking for patients and guests, approval by reception, and the public website

Date: 2026-10-29. Status: proposed (Phase 0 of `docs/PUBLIC-SITE-PLAN.md`, awaiting the owner's
review). Extends 0016 (portal) and 0023 (center page) without weakening their rules; related: 0005
(abuse control), 0028 (how the public reaches a center), 0021 (notifications).

Markers: **[SETTLED]** is the owner's decision (plan section 7 and the Phase 0 brief, binding).
**[DESIGN DECISION, owner may veto]** is a recommendation adopted from the Phase 0 review. Anything
unmarked follows from those. Numbers marked "proposed" are starting defaults, editable in the
settings row.

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
2. **Approval.** `require_approval` defaults **on**. An online booking, **by a signed-in patient or
   a guest**, enters `requested` and becomes `booked` only when reception approves.
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
- **[DESIGN DECISION, owner may veto] Permission migration keeps every grant.** A data migration
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
- **[DESIGN DECISION, owner may veto] The constraint migration pre-checks live data.** Before
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
  minutes (proposed), so a request cannot be created already expired (`starts_at - lead` is at
  least "now" by the lead rule, so a slot just past the lead time would otherwise have a zero
  window).
- Idempotency: public booking POSTs require an `Idempotency-Key` (UUID); same key and same body
  returns the stored answer, same key and a different body is `409 IDEMPOTENCY_MISMATCH`; rows
  expire after 24 h.

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

### E. State machine
`requested -> booked | cancelled(rejected, expired, cancelled by the booker, cancelled on behalf)`;
`booked -> arrived | rescheduled | cancelled | no_show`; every other edge is refused (tested edge
by edge). Reject and cancel carry a reason code in category `appointment_cancel`, a note, the actor
and the time (invariant 4); expiry is the system actor with reason `ONLINE_REQUEST_EXPIRED`.
`REQUESTED` is added to `AppointmentStatus` in the same migration as the exclusion constraint
(the constraint names the value). A booking creates **no** patient, visit, service line, invoice
or payment (asserted by row counts), so the seven invariants are untouched.

### F. [DESIGN DECISION, owner may veto] Abuse limits for guest booking
Guests are anonymous and the phone is unverified, so the per-phone cap alone is spoofable (change a
digit). Added limits, all editable in the settings row, with proposed defaults:
- **Pending requests per doctor per day:** at most 10 `requested` rows for one doctor on one
  day; further attempts are refused with `ONLINE_DOCTOR_DAY_FULL`, so a flood cannot lock a whole
  day out of real patients.
- **Requests per client address per day:** at most 5 (the address is `client_ip`, which needs the
  proxy configuration of 0028 decision 6), on top of the existing per-address 429 limits.
- **Bulk "reject all from this phone".** An inbox action that rejects every open request with the
  same normalized phone in one audited operation (one reason code, one note, the actor, the time on
  each row). It does not block the phone; automatic blocking stays out of V1 as decided.
- **Offline proof-of-work instead of a CAPTCHA.** The booking form asks `GET /api/portal/challenge`
  (a signed, expiring, single-use challenge) and the browser finds a nonce so that
  `SHA-256(challenge + nonce)` has N leading zero bits (proposed 18, adjustable, raised for an
  address that is near its caps); the POST carries challenge and nonce and the server verifies in
  constant time. No third-party service, so it works on a LAN and offline. Two honest limits: it
  slows scripted floods, it does not stop a determined attacker (the caps, reception review and
  expiry are the real defense); and `crypto.subtle` exists only in secure contexts, while a LAN
  install may serve plain HTTP, so the hash runs in a bundled pure-JavaScript SHA-256 in a worker.

### G. [DESIGN DECISION, owner may veto] Staff actions and retention
- **Reissue guest PIN** (inbox, reason required, audited): the old PIN stops working, a new one is
  shown once to the staff member, who reads it to the guest.
- **Cancel on behalf** of a booker (reason code and note), the same service as any cancellation.
- **Retention.** `guest_retention_days` (proposed 90, editable): the hourly `maintenance` anonymizes
  guest bookings that were never linked to a file and ended `cancelled` or `expired` more than that
  long ago (`contact_name` replaced by a fixed placeholder so the has-person check still holds,
  `contact_phone` and `notes` cleared, `GuestBookingAccess` deleted), and writes one `PortalEvent`
  with counts only. **Limit, stated plainly:** the appointment history table
  (`visits_appointmentevent`) is append-only by trigger (ARCHITECTURE 4.9), so the earlier copies
  of the name and phone in that history are not erased. Whether that satisfies the center's data
  duty is the owner's call; the alternative (exclude the contact fields from tracking for guest
  rows, or lift the trigger for this one purge) costs audit integrity and is not proposed.
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

## Consequences
- Existing portal booking changes behavior on upgrade: with `require_approval` on by default, a
  signed-in patient's booking is now `requested`, not `booked`. The data migration seeds the
  settings row so that an install which already uses portal booking is told in the release notes;
  the owner may prefer to seed `require_approval = false` for existing installs (open question in
  the impact document).
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
