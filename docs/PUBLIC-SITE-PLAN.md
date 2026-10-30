# Work order: public center website, online booking and patient tracking

Status: **COMPLETE (2026-10-30).** Phases 0 to 6 shipped; what was built, and every deviation, is
in the "as built" sections of ADRs 0028 and 0029. The text below is the plan as written, kept for
the record. Original status line: PLAN ONLY. Nothing in this document has been executed. It is an enhanced, evidence-based
rewrite of the original request, grounded in the code on `main` as of 2026-10-29. Claude Code
executes it phase by phase with the `ship-feature` skill; Musab reviews Phase 0 before any code.

**Amended 2026-10-29 by the owner's Phase 0 review.** Where this plan and ADRs 0028 / 0029 differ,
the ADRs win. In particular: one domain and one host serve the website, booking, the portal and
the staff app (no public listener, no separate public name); the edge of D1 and Phase 6 is for
LAN-only installs; `core.manage_public_site` (not `core.manage_settings`) edits the site settings;
`require_approval` is seeded off on an existing install.

Read first, in order: `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/FLOW.md`, ADRs 0005, 0016, 0023,
0027. Every rule in them stays binding. Where this plan extends a rule it says so and names the ADR
that must record it.

---

## 0. What already exists (evidence, not assumptions)

The original request reads as green-field. It is not. Verified on `main`:

| Request item | Already on `main` | Where |
|---|---|---|
| Public center page (name, logo, about, hours, departments, doctors + clinic days, announcements, contact, address, WhatsApp, e-mail, directions), per-section switches, hidden departments/doctors, admin screen, rate-limited public endpoints | **Done** (ADR 0023) | `core.CenterPage`, `core.Announcement`, `GET /api/portal/center-page`, `/administration/center-page`, `src/portal/pages/CenterPage.tsx` |
| Patient area: sign-in, home, appointments, booking, results (approved only), prescriptions, invoices (patient share only), receipts, balance | **Done** (ADR 0016) | `apps/portal/*`, `src/portal/*` |
| Patient booking: doctor → day → free slot, lead time, horizon, max open bookings, one per doctor per day, cancel before cut-off, locked per person and per doctor, `APPOINTMENT_CONFLICT` on a race | **Done** for *existing patients* | `apps/portal/services.book_appointment`, `domain/portal.check_booking` (Hypothesis), `apps/visits/services.book_appointment` |
| Staff appointments: book, reschedule, cancel (reason code), day view, convert to visit on arrival (`convert_appointment` requires a patient file: a contact caller is registered first, never auto-merged) | **Done** | `apps/visits/services.py` 698-860, `/api/visits/appointments*` |
| Appointment without a file (`contact_name` + `contact_phone`, `patient = NULL`) | **Model supports it**; only staff use it today | `visits.Appointment` check `visits_appointment_has_person` |
| Patient/staff session isolation, uniform 401, per-file and per-address throttles, append-only `PortalEvent` | **Done** | ADR 0005, 0016; `apps/portal/security.py` |
| Public receipt check by HMAC token | **Done** | `GET /api/portal/verify` |
| Vendor marketing page per deployment (`MARKETING_SITE`) | **Done** (ADR 0027): this is the *vendor's* sales page, not the center's website. Do not conflate them. | `apps/ops`, `src/features/marketing` |
| Staff in-app notifications with kinds/recipients table | **Done** (ADR 0021) | `core.Notification`, `apps/core/notification_kinds.py` |

What "order" means in this system (verified): an **order is a `orders.ServiceLine`** on a visit
(consultation, lab, procedure, drug, consumable, bed). It carries two orthogonal statuses,
`billing_status` (`unbilled → invoiced ⇄ settled → credited`) and `fulfilment_status`
(`pending → in_progress → performed | cancelled`), plus a derived display `state`. There is no
separate "Order" header model. Lab results hang off lines through `lab.ResultSet/ResultVersion`
(patient sees approved versions only); pharmacy fulfilment is `Dispense/DispenseLine`. Patient
tracking of "orders" therefore means tracking `ServiceLine` fulfilment per visit, which the portal
partly does already (results list, prescriptions "dispensed" flag).

### 0.1 What does NOT exist (the real gaps)

1. **No public reachability.** Every center install is LAN-only with internal TLS
   (`infra/Caddyfile`); "no runtime internet dependency" is a hard rule (`CLAUDE.md`, ARCHITECTURE 8).
   A public website and internet booking need the center's server (or a proxy of it) to be
   reachable from the internet. This is the single biggest decision and it is infra + ADR, not a
   feature flag.
2. **No patient channel.** `Notification` is staff-only, in-app. SMS is FEATURES 0.14 "Later";
   there is no e-mail sending. So there is no OTP, no confirmation SMS, no reminder. Any "verify
   identity through the system's supported authentication method" for a *new* patient has no
   method to use today.
3. **No identity for new patients.** Portal credentials are file number + phone + receipt code
   issued by a cashier. A person who has never visited has none of the three.
4. **No approval state** on `Appointment` (`booked, arrived, cancelled, no_show, rescheduled`).
5. **No doctor leave / blocked periods.** Availability = `DoctorSchedule` rows minus booked
   appointments. `valid_from/valid_to` on a schedule is the only way to express absence.
6. **No per-service online eligibility.** Portal booking is per *doctor* only (consultation slot).
   Services (lab, procedures) are not bookable, and the slot model has no service duration.
7. **No idempotency** on public POSTs (a retry after a timeout can create two bookings; today the
   per-doctor-per-day rule limits damage for signed-in patients, not for guests).
8. **No reschedule** in the portal (staff only).
9. **No multi-branch.** FEATURES "out of scope": multi-branch sync. One center, one server.
10. **No online payment.** No gateway, no bank integration (FLOW 10, FEATURES out of scope).
    Prices are deliberately kept off the public page (ADR 0023 "Not built").
11. Website sections missing from `CenterPage`: hero imagery, facilities, "why us", services per
    department, doctor qualifications/photo, insurance providers, FAQ, testimonials,
    accessibility note, policies/privacy footer.
12. Booking rules (`lead`, `horizon`, `max_open`, `cancel_cutoff`) are **env settings**
    (`apps/portal/conf.py`), not administrator-editable.

---

## 1. Product decisions (settled in §7; Phase 0 records them as ADRs)

**D1. Topology: how the public reaches the center's server.**
Recommended: **inbound-only edge**. A small VPS (or the vendor's existing `stingdev.pro` host)
runs Caddy as a reverse proxy over an outbound tunnel from the center's server (WireGuard or
Cloudflare Tunnel; the center's server initiates, so no inbound port, no public IP, no router
change). The edge proxies **only** `/portal*`, `/verify*`, `/api/portal/*`, `/api/ops/site` and
static assets. Staff routes (`/api/auth`, `/api/visits`, …, `/administration`, `/sign-in`) are
refused at the edge with 404, so the staff attack surface never leaves the LAN. When the tunnel is
down the edge serves a static fallback page (center name, phone, "online booking temporarily
unavailable") from a cached copy of `center-page`. Alternative (rejected for V1): a separate
public service with a replicated read model and an async booking queue. It survives outages but
needs a second deployable, a sync protocol and conflict handling; bookings become "pending until
synced" with no real availability. Record as **ADR 0028**, amending ARCHITECTURE 8: the *app*
still makes no outbound fetch; the tunnel is optional infra, opt-in per deployment, documented in a
runbook with the exact exposed path list and a test that the edge refuses staff paths.

**D2. Identity for people without a file ("guest booking").**
Recommended: a guest books as an `Appointment` with `contact_name`, `contact_phone`,
`patient = NULL` (the existing model), and receives a **booking reference + 6-digit PIN** shown
once on the confirmation screen (same pattern as the receipt code: PIN stored as a password hash,
never re-shown, throttled like portal sign-in). Reference + PIN opens a **guest view limited to
that one booking** (status, time, doctor, cancel/reschedule within rules). It never opens a patient
file. Phone is **unverified** (no SMS): the plan states this limitation plainly; reception verifies
identity at arrival when it registers the caller or links the booking to an existing file
(`convert_appointment` already demands a file and refuses a mismatch; no auto-merge by name or
phone, matching FLOW 1 "duplicate warning, merge by supervisor only"). Existing patients keep
signing in with file + phone + code; their bookings appear in their file as today. Full tracking
(orders, results, receipts) stays behind the file sign-in only. **ADR 0029.**

**D3. Approval.** Add `AppointmentStatus.REQUESTED`. An online booking enters `requested` when
`require_approval` is on, otherwise `booked`. A requested booking **holds its slot** (otherwise
approval is meaningless) and carries `expires_at` (= min(starts_at − lead, created + N hours,
setting)); `maintenance` expires unanswered requests to `cancelled` with reason
`ONLINE_REQUEST_EXPIRED` and the free slot returns. Staff approve (→ `booked`) or reject
(→ `cancelled`, reason code category `appointment_cancel`, note) from a reception inbox.
`available_slots` treats `requested` as taken.

**D4. Three independent switches** (new `core.PublicSiteSettings` singleton, editable by
`core.manage_settings`, pghistory-tracked): `site_enabled`, `online_booking_enabled`,
`patient_tracking_enabled`, plus the booking rules moved from env to this row (`lead_minutes`,
`horizon_days`, `max_open`, `cancel_cutoff_hours`, `reschedule_allowed`, `reschedule_cutoff_hours`,
`require_approval`, `request_ttl_hours`, `guest_booking_enabled`, `max_guest_bookings_per_phone`).
Enforced in **services and routers**, never only in the UI (§5 tests). Behavior when off:

| Switch off | Public effect | Operational effect |
|---|---|---|
| `site_enabled` | `/portal` shows only the sign-in card (pre-ADR-0023 behavior) if tracking is on, else a one-line "online services are not available" page. `GET /api/portal/center-page` answers `404 SITE_DISABLED`. Edge fallback shows nothing but the center name. | None. `CenterPage` content, media, FAQ, testimonials are kept. Staff sign-in panel still reads name/logo through a separate minimal endpoint (`center-identity`). |
| `online_booking_enabled` | Booking buttons hidden; `POST /api/portal/appointments`, guest booking and slot endpoints answer `409 ONLINE_BOOKING_DISABLED`. | Existing online bookings stay `booked`/`requested` and are managed by staff as any appointment. Patients can still *view and cancel* them if tracking is on. |
| `patient_tracking_enabled` | Portal sign-in and every patient endpoint answer `409 PORTAL_DISABLED`; open portal sessions are ended; guest booking view still works if booking is on. | Cashier "issue access code" hidden and refused. Records untouched. |

**D5. Scope exclusions for V1** (state them in the ADR): branches (single center); online
payment and fees display (no gateway; prices stay off the site per ADR 0023 — show "fees are
paid at reception" and the cancellation policy text instead); service-level booking (lab,
procedures) — V1 books **doctor consultation slots only**, which is what the slot model
supports; SMS/e-mail (channel interface prepared, no provider); map embeds (plain link to a
maps URL opened on the visitor's phone is allowed like `wa.me`).

**D6. Content model stays "fixed sections, not a CMS"** (ADR 0023 decision kept). New sections
are typed fields/rows with bilingual text and size caps, not a page builder.

---

## 2. Impact on business logic (what changes, what must not)

- **Patient record** is created only by reception (`patients.services`), never by the website.
  A guest booking creates no `Patient`. Linking happens at arrival. The seven invariants are
  untouched: a booking creates **no visit, no service line, no invoice, no payment**.
- **Visit** is created only by `convert_appointment` at arrival (existing). Online booking never
  implies check-in. The consultation `ServiceLine` is created by `create_visit` as today
  (`requested` → cashier invoices → `paid` → queue).
- **Queue**: unchanged. A converted appointment enters the queue exactly as a walk-in; the day
  view already shows appointments beside walk-ins. No "online patients first" rule unless Musab
  asks for it (unresolved, §7).
- **Availability** = `DoctorSchedule` (active, valid range) − appointments in `booked|requested`
  − new `DoctorTimeOff` ranges. Slot length = `DoctorSchedule.slot_minutes`. Doctor must be
  `active` and `online_bookable` (new flag, default false, so going live exposes nobody by accident).
- **Double booking**: keep the per-doctor row lock + `_check_slot`; add a database backstop:
  `EXCLUDE USING gist (doctor_id WITH =, tstzrange(starts_at, ends_at) WITH &&) WHERE (status IN
  ('booked','requested'))` (needs `btree_gist`; migration in `visits`). Mapped to
  `409 APPOINTMENT_CONFLICT` through `api.errors.DB_GUARD_CODES`.
- **Idempotency**: public booking POSTs require an `Idempotency-Key` (UUID, client-generated,
  kept across retries). New `portal.IdempotentRequest(key, scope, request_hash, status, body,
  created_at)`; same key + same hash → stored answer (same booking); same key + different hash →
  `409 IDEMPOTENCY_MISMATCH`; rows expire after 24 h in `maintenance`. No charges exist, so "safe
  retries" is bookings only.
- **Cancellation / reschedule by patient**: existing `check_cancel`; add `check_reschedule`
  (same cut-off family, new slot validated like a booking, old appointment → `rescheduled`,
  `rescheduled_from` link, both in one transaction holding both doctor locks in id order).
- **No-show**: staff action exists (`no_show`). Patient sees "missed". A center may later limit
  guests with repeated no-shows (not in V1; listed in §7).
- **Refunds**: nothing to refund; no money moves online.
- **Notifications**: staff kinds added to `notification_kinds.py`: `online_booking_requested`
  (receptionists), `online_booking_cancelled_by_patient` (receptionists). Patient side: new
  `portal.PatientNotice` (file-scoped, in-portal inbox: confirmed, approved, rejected with reason
  text chosen by staff, rescheduled, result published) written through one
  `patients.notify(person, kind, payload)` service with a channel list `["portal"]`; SMS is a
  future channel behind the same call. "Failed notification" handling in V1 = none needed
  (database write in the same transaction).
- **Permissions**: new codes `visits.manage_online_bookings` (receptionist, manager),
  `core.manage_public_site` (admin, manager; separate from `core.manage_settings` so a marketing
  person can edit the site without touching policy), `core.approve_testimonial` (manager).
  Portal/guest endpoints keep `PortalAuth` / new `GuestAuth`; staff endpoints keep session auth.
  The two never mix (existing tests extended).
- **Audit**: pghistory on every new model; `PortalEvent` kinds added: `guest_booking_created`,
  `guest_view`, `guest_view_refused`, `guest_locked`, `booking_rescheduled`.
  Reception approve/reject records actor, time, reason (invariant 4 style).

---

## 3. Data changes (migrations)

| App | Change |
|---|---|
| `core` | `PublicSiteSettings` singleton (D4). `CenterPage` + fields: `hero_title_ar/en`, `hero_text_ar/en`, `facilities` (JSON rows `{name_ar,name_en}` ≤ 20), `reasons` (JSON rows ≤ 8), `accessibility_ar/en`, `privacy_ar/en`, `cancellation_policy_ar/en`, `maps_url`, `show_services`, `show_insurance`, `show_faq`, `show_testimonials`, `show_facilities`, `show_policies`. New `CenterMedia` (image file ≤ 2 MB, kind `hero|gallery|doctor`, sort, alt_ar/en, served by `/api/portal/center-media/{id}?v=`, cacheable 1 h like the logo). New `CenterFaq` (question/answer ar+en, sort, active). New `Testimonial` (text ar/en, author display name, `approved_by`, `approved_at`, `active`; shown only when approved; never free-text from the public: staff enter them). `DoctorProfile` + `qualifications_ar/en`, `bio_ar/en` (≤ 400), `photo` (CenterMedia FK), `online_bookable`. `Payer` + `show_on_site`. `Service` + `show_on_site` (name only, no price). |
| `visits` | `AppointmentStatus.REQUESTED`; `Appointment` + `source` (`staff|portal|guest`), `expires_at`, `approved_by/at`, `guest_access` (1:1 to portal model below); exclusion constraint; `DoctorTimeOff(doctor, starts_at, ends_at, reason_ar/en, created_by)` with overlap exclusion per doctor; `ReasonCode` rows `ONLINE_REJECTED`, `ONLINE_REQUEST_EXPIRED`, `PATIENT_RESCHEDULE`. |
| `portal` | `GuestBookingAccess(appointment 1:1, reference unique 10 chars base32 from `secrets`, pin_hash, failures, locked_at, created_at)`; `IdempotentRequest`; `PatientNotice`; `PortalThrottle` scope `guest`. |

Every new table with user-visible state is pghistory-tracked; `core/tests/test_schema.py`'s
untracked-model allowlist is updated deliberately, not silently.

---

## 4. API changes

Public, no session (rate-limited per address like `center-page`):
- `GET /api/portal/center-page` — extended answer (pinned field set test updated; still never
  prices, registration/tax numbers, staff beyond shown doctors).
- `GET /api/portal/center-identity` — name + logo only; works even when `site_enabled` is off (staff sign-in panel).
- `GET /api/portal/center-media/{id}`.
- `GET /api/portal/booking/doctors`, `/booking/doctors/{id}/days`, `/booking/doctors/{id}/slots?on=` — already exist behind the portal session; **make them public-readable** when booking is on (slots reveal only free times, no patient data).
- `POST /api/portal/guest-bookings` (`Idempotency-Key` required) → `{reference, pin (once), status, starts_at, doctor}`.
- `POST /api/portal/guest-bookings/sign-in` `{reference, pin}` → guest cookie (`hospital_guest`, path `/api/portal/guest`, same hardening as ADR 0016: hashed token, idle/max life, uniform 401 `GUEST_INVALID_CREDENTIALS`, lock after 5 failures per reference, per-address 429).
- `GET /api/portal/guest/booking`, `POST …/cancel`, `POST …/reschedule`, `POST …/sign-out`.

Patient session (existing `PortalAuth`):
- `POST /api/portal/appointments/{id}/reschedule`; `GET /api/portal/notices`, `POST …/{id}/read`;
  `GET /api/portal/visits/{id}/timeline` (appointment → visit → lines with patient-facing states → payments; §5 mapping).

Staff:
- `GET /api/visits/online-bookings?status=requested|booked&day=` (inbox), `POST …/{id}/approve`,
  `POST …/{id}/reject {reason_code, note}`, `POST …/{id}/link-patient {patient_id}` (explicit, audited; refuses when the appointment already has a different file).
- `GET/PUT /api/core/public-site-settings`; CRUD for `CenterFaq`, `Testimonial` (+ `approve`), `CenterMedia`, `DoctorTimeOff`; patches on `DoctorProfile`, `Payer`, `Service` for the new flags.
- Operation ids follow `<app>_<verb>_<thing>`; `make api` regenerates `schema.d.ts`; CI drift check stays.

---

## 5. Patient-facing status mapping (keep the four families distinct)

| Family | Internal | Patient sees (ar/en keys in `portal` namespace) |
|---|---|---|
| Booking | `requested` / `booked` / `arrived` / `rescheduled` / `cancelled` (+reason class) / `no_show` / expired | "awaiting approval" / "confirmed" / "you were received" / "moved to …" / "cancelled by you" vs "cancelled by the center" / "missed" / "request expired" |
| Visit | `open` / `closed` / `cancelled` | "at the center today" / "completed" / "cancelled" |
| Order (`ServiceLine`) | fulfilment `pending` (and billing `unbilled|invoiced`) / `pending` + `settled` / `in_progress` / `performed` / `cancelled` | "ordered, pay at reception" / "paid, waiting" / "in progress" / "done" (lab: "result published" only when an approved `ResultVersion` exists) / "cancelled" |
| Payment | invoice patient due, paid, outstanding; receipt `confirmed|pending|void` | "paid" / "payment under verification" / "outstanding" |

Rules: a booking never shows "received", "paid" or "done" on its own; those come only from
`Visit`, `Payment`, `ServiceLine` rows linked through `Visit.appointment`. Pure mapping functions
in `domain/portal_status.py`, Hypothesis-tested for totality (every combination maps, never to an
"unknown").

---

## 6. Phases (each is one or more `feat/<phase>-<slug>` branches shipped with `ship-feature`)

**Phase 0 — Impact analysis and ADRs (no code).**
Deliver `docs/adr/0028-public-edge-topology.md`, `docs/adr/0029-online-booking-guest-access-and-public-site.md`,
and `docs/inspection/public-site-impact.md` (the table in §0 re-verified against the current
`main`, every file path cited, every existing test that must change listed). Update `FEATURES.md`
(2.5 and 15.2 lines, new 15.3 "public website", 15.4 "guest booking") and `FLOW.md` with a short
"الحجز عبر الإنترنت" subsection under step 1. **Stop for Musab's review.**

**Phase 1 — Switches and enforcement.** `PublicSiteSettings`, admin screen
`/administration/public-site`, `require_site`, `require_online_booking`, `require_tracking`
guards used by services (not only routers), `center-identity` endpoint, portal/SPA behavior per
D4 table, booking rules read from the row (env values become migration defaults; `conf.py` keeps
only abuse-control settings). Tests: every public and patient endpoint × each switch off → the
exact code; sessions ended when tracking turns off; staff endpoints unaffected.

**Phase 2 — Website content.** Models and admin screens for the new sections (§3), public
answer extension, `CenterPage.tsx` sections (hero, about, facilities, reasons, departments →
services (names), doctors with qualifications/photo/clinic days, hours, insurance, FAQ,
testimonials, accessibility, contact/address/map link, footer with policies). Empty or hidden
sections render nothing (existing sparse-state pattern). Images as `CenterMedia`, never external
URLs. E2E: full/sparse/empty variants × 3 viewports × 3 themes × 2 languages, no horizontal
scroll; axe pass on the page; pinned-fields test for the public answer.

**Phase 3 — Availability hardening.** `DoctorTimeOff` (+ staff screen on the doctor's schedule
page), `online_bookable`, exclusion constraint, `requested` counted as taken, portal reschedule,
`domain/portal.check_reschedule`. Tests: Hypothesis over schedules × time-off × bookings
(no offered slot overlaps anything); 8-thread concurrent booking of one slot on real Postgres →
exactly one row, others `APPOINTMENT_CONFLICT`; direct SQL insert of an overlapping row is
refused by the constraint.

**Phase 4 — Guest booking journey and reception inbox.** Public slot endpoints, guest booking
POST with idempotency, reference + PIN, guest session and view, cancel/reschedule, `requested`
flow with `expires_at` and `maintenance` expiry, staff inbox (`/visits/online-bookings`), approve /
reject / link-patient, arrival conversion from the inbox, staff notifications. Portal pages:
`/portal/book` (public entry: doctor → day → slot → name + phone → review with cancellation policy
→ confirmation with reference + PIN shown once), `/portal/booking` (guest sign-in and view).
Tests: idempotent replay returns the same booking; mismatch → 409; uniform 401 and lock for guest
sign-in; guest cookie never reaches patient or staff endpoints and vice versa (three-way matrix);
state machine `requested → booked | cancelled(expired|rejected)`, `booked → arrived | rescheduled |
cancelled | no_show`, every other edge refused; a guest booking creates no Patient, Visit,
ServiceLine, Invoice or Payment row (asserted by counts); per-phone and per-address caps.

**Phase 5 — Patient tracking.** `/portal/visits/{id}` timeline, `domain/portal_status.py`,
`PatientNotice` inbox with unread badge, result-published notice hooked on
`lab.services.approve_result` (existing approval path, nothing new published), booking notices.
Tests: mapping totality; cross-patient 404 for timeline and notices; a notice is written in the
same transaction as its event (rollback leaves none).

**Phase 6 — Edge deployment and handover.** `infra/edge/` (Caddyfile with the exact path
allowlist, fallback page, tunnel unit), `docs/runbooks/public-edge.md` (enable, disable, rotate,
what is exposed, how to verify), `infra/tests` case that the edge config refuses `/api/auth/*`,
`/api/visits/*`, `/administration*`, `/sign-in`; `docs/guides/` pages for reception (online
inbox) and administrator (public site); `CHANGELOG.md`, `PROGRESS.md`.

Definition of done per phase: `make check` green, e2e for touched areas green at 375/768/1280,
ar/en key parity, no new raw colors or physical-direction utilities, OpenAPI committed, ADR
cross-references in code docstrings, PR squash-merged to `main`.

---

## 7. Product decisions — SETTLED by Musab on 2026-10-29 (binding for every phase)

1. **Topology.** The landing page and the booking page are optional features the administrator
   switches on (`site_enabled`, `online_booking_enabled`). They become public only when the
   deployment is hosted on a server reachable from the internet. The application does not care
   how: the edge/tunnel of D1 is the recommended, documented way (Phase 6), but the switches and
   the feature work the same on a plain internet-facing deployment. A LAN-only install may switch
   them on and get them on the LAN only.
2. **Approval.** Every online booking is checked by reception: `require_approval` defaults to
   **on**; a booking enters `requested` and becomes `booked` only when reception approves.
3. **Guest booking is allowed** (new patients without a file), per D2. Cap: 2 open guest
   bookings per phone (`max_guest_bookings_per_phone`, editable). No automatic phone blocking for
   no-shows in V1.
4. **No queue priority** for online bookings; same queue as walk-ins.
5. **No fees on the site**; the page shows "fees are paid at reception" and the cancellation
   policy text.
6. **Testimonials: yes**, staff-entered and manager-approved only (`core.approve_testimonial`);
   never submitted from the public.
7. **Reschedule by the patient: allowed**, same cut-off as cancellation, for signed-in patients
   and guests alike.
8. **Request expiry: 24 hours** before the slot by default (`request_ttl_hours`, editable, never
   later than the booking lead time).

## 8. Limitations to state in the handover

- No SMS/e-mail: confirmations live only on the confirmation screen and in the portal inbox.
- Guest phone numbers are unverified until arrival.
- One center, consultation slots only; lab/procedure booking and multi-branch are not in V1.
- The website is down when the center's internet is down (fallback page only).
- No online payment; no fees online.
