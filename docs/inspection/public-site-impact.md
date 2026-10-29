# Impact analysis: public website, online booking and patient tracking (Phase 0)

Date: 2026-10-29. Base: `main` at `e26929b` (PR #23). Method: read the code and tests named
below; no application code, migration, server or deployment was touched. Where a statement was
**not** verified it says so. Companion documents: `docs/PUBLIC-SITE-PLAN.md` (the work order, with
the owner's settled decisions in section 7), ADR 0028 (topology) and ADR 0029 (booking and site).
Paths are relative to the repository root; `file:N` is a line on `e26929b`.

**Owner review, 2026-10-29.** The owner decided the open items of section 7 (one domain and one
host, no public listener; `require_approval` seeded off for existing installs; guest data left in
the append-only history accepted; the proposed numbers accepted). Sections 4, 6 and 7 are updated
to match; ADR 0028 and 0029 are accepted.

## 1. The plan's section 0 table, re-verified

Every row of the plan's table holds, with the corrections noted. "Where" cites the code.

| Request item | Verdict | Evidence |
|---|---|---|
| Public center page, per-section switches, hidden departments/doctors, admin screen, rate-limited public endpoints (ADR 0023) | **Holds.** | Model `CenterPage` `backend/apps/core/models.py:218-256` (switches `show_*`, `hidden_department_ids`, `hidden_doctor_ids`), `Announcement` `:258`. Public read `GET /api/portal/center-page` `backend/apps/portal/api.py:187-201`, logo `:204-221`, built by `backend/apps/portal/queries.py:542`; per-address limit `check_public_page_rate` `backend/apps/portal/services.py:720`. Staff edit: `core_get_center_page` / `core_update_center_page` / announcements `backend/apps/core/api.py:410-470`, all `@require_perm("core.manage_settings")`. Screen `frontend/src/features/admin/pages/CenterPageSettingsPage.tsx`, nav `frontend/src/features/admin/sections.ts:70-75`. Public page `frontend/src/portal/pages/CenterPage.tsx`, mounted at `/portal` `frontend/src/portal/routes.tsx` (route `center`). Pinned field set tested `backend/apps/portal/tests/test_center_page.py:127-141`. |
| Patient area: sign-in, home, appointments, booking, approved results, prescriptions, invoices (patient share), receipts, balance (ADR 0016) | **Holds.** | Patient operations `backend/apps/portal/api.py:333-520` (`/me`, `/summary`, `/appointments`, `/results`, `/prescriptions`, `/invoices`, `/receipts`, `/balance`), all registered through `_patient_op` (`:88-93`). Frontend `frontend/src/portal/pages/*`. |
| Patient booking: doctor, day, free slot, lead time, horizon, max open, one per doctor per day, cancel before cut-off, locked per person, `APPOINTMENT_CONFLICT` on a race | **Holds, for existing patients only.** | `book_appointment` `backend/apps/portal/services.py:586-630` (person row lock `:609`, `check_booking` `:614`), `check_booking` and `BookingRules` `backend/domain/portal.py:200-292`, `cancel_appointment` `backend/apps/portal/services.py:633`, staff `book_appointment` with doctor lock `backend/apps/visits/services.py:698-739`. Booking reads are patient-session only: `/doctors`, `/doctors/{id}/days`, `/doctors/{id}/slots` `backend/apps/portal/api.py:399-430`. |
| Staff appointments (book, reschedule, cancel with reason code, day view, convert on arrival; a contact caller is registered first) | **Holds.** | `backend/apps/visits/services.py:651-872` (`_check_slot` `:678`, `reschedule_appointment` `:749`, `cancel_appointment` `:776`, `mark_appointment_no_show` `:811`, `convert_appointment` `:819` raises `PATIENT_REQUIRED` / `APPOINTMENT_PATIENT_MISMATCH`, `available_slots` `:841`), router `backend/apps/visits/api.py:277-440`. |
| Appointment without a file (`contact_name`, `contact_phone`, `patient = NULL`) | **Holds**; used only by staff. | `Appointment` `backend/apps/visits/models.py:218-291`, check `visits_appointment_has_person` `:274-277`. |
| Session isolation, uniform 401, per-file and per-address throttles, append-only `PortalEvent` | **Holds.** | `backend/apps/portal/security.py:16`, `PortalThrottle` `backend/apps/portal/models.py:130-170`, `PortalEvent` `:170-200`. |
| Public receipt check by HMAC token | **Holds.** | `backend/apps/portal/api.py:167-181`, `backend/apps/portal/services.py:746`. |
| Vendor marketing page per deployment (`MARKETING_SITE`) | **Holds**; not the center's website. | `backend/config/settings.py:184-188`, `GET /api/ops/site` `backend/apps/ops/api.py:64-80`, `frontend/src/lib/site.ts`, `frontend/src/app/routes.tsx:57-80`, `frontend/src/features/marketing/`. See finding (c). |
| Staff in-app notifications with a kinds table | **Holds.** | `core.Notification` `backend/apps/core/models.py:614`, `backend/apps/core/notification_kinds.py`. |

**Plan section 0.1 (the real gaps), re-verified:**
1. No public reachability: `infra/Caddyfile` (`local_certs`, internal TLS, `:80` default) and ARCHITECTURE section 8. Holds. Nuance the plan omits: the OVH deployments are already public behind a host Caddy (project memory `deployment-healtfull`; **not re-read from the server**).
2. No patient channel: no `send_mail` / `EMAIL_BACKEND` / `smtplib` anywhere under `backend/apps` or `backend/config`; `Notification` is per staff user (`models.py:614-626`). Holds.
3. No identity for new patients: codes are issued from a receipt (`backend/apps/portal/api.py:232`). Holds.
4. No approval state: `AppointmentStatus` `backend/apps/visits/models.py:209-214` has five values. Holds.
5. No doctor time off: no such model; only `DoctorSchedule.valid_from/valid_to` (`:308-309`). Holds.
6. Per-doctor only: `bookable_doctor` `backend/apps/portal/services.py:572`. Holds.
7. No idempotency: no key anywhere in `backend/apps/portal/`. Holds.
8. No portal reschedule: `backend/apps/portal/api.py` has `cancel` only (`:386`). Holds.
9. to 10. Out of scope items: FEATURES "Explicitly not in V1". Holds.
11. Center page sections missing: `CenterPage` fields `backend/apps/core/models.py:218-256` have no hero, facilities, FAQ, testimonials. Holds.
12. Booking rules are environment settings: `backend/apps/portal/conf.py:69-75` (`booking_rules()` reads `PORTAL_BOOKING_*`). Holds.

## 2. The three open points

### (a) Is the proposed `btree_gist EXCLUDE` constraint safe?

**Findings.**
- `Appointment` has `ends_at` (non-null, `backend/apps/visits/models.py:239`) and a database check
  `ends_at > starts_at` (`:271-273`), so the range `tstzrange(starts_at, ends_at)` is always
  valid and non-empty.
- **Staff cannot intentionally overbook.** There is no override flag, parameter or role anywhere:
  `grep` for overbook / double-book finds only a test named "never double books"
  (`backend/apps/visits/tests/test_services.py:630`). `book_appointment` always calls
  `_check_slot` (`backend/apps/visits/services.py:727`), which refuses any overlap with a `booked`
  appointment of the doctor (`:686`, `starts_at < end and ends_at > start`), under a
  `select_for_update` on the `DoctorProfile` row (`:725`, present since the phase-1 commit). The
  staff API accepts an explicit `ends_at` (`AppointmentIn.ends_at`, `backend/apps/visits/schemas.py:387`)
  but it goes through the same check. Reschedule marks the old row `rescheduled` before it books the
  new one in the same transaction (`:757-761`), so a move onto an overlapping time does not clash
  with itself. `update_appointment` changes notes and contact only (`AppointmentPatch`, `schemas.py:394`).
  There is no path that un-cancels or re-opens an appointment.
- Statuses that leave `booked` (`arrived`, `no_show`, `cancelled`, `rescheduled`) free the slot in
  the application (only `BOOKED` is checked, `services.py:686`), and the constraint's `WHERE
  status IN ('booked','requested')` matches that.
- The half-open range `[)` of `tstzrange` makes back-to-back slots legal, the same as the
  application check.
- **Can existing rows overlap?** Through the application: not expected. Possible sources of
  overlaps are rows written outside `book_appointment`: direct SQL, a restore of edited data, or
  test code (`Appointment.objects.create` appears in tests only: `backend/apps/patients/tests/test_services.py:267`,
  `backend/apps/visits/tests/test_models.py:70-72`; the demo seeder uses `visits.book_appointment`,
  `backend/apps/core/demo/activity.py:1012`). There is no appointment import
  (`backend/apps/imports` mentions none). **I could not query a live database in Phase 0**, so
  whether production or the demo hold an overlapping pair is **unverified**. This is why ADR 0029
  adds the pre-check that fails with a list of conflicts (decision "The constraint migration
  pre-checks live data").
- **Other facts the plan missed.**
  - `btree_gist` is not created anywhere today (`pg_trgm` is, `backend/apps/core/migrations/0005_search_functions.py`; `btree_gin` appears only in `infra/tests/test_db_roles.sh:225`). It is a trusted extension on PostgreSQL 13+, so the migration owner role can create it without superuser, but the migration needs `BtreeGistExtension()` and the infra role test (`infra/tests/test_db_roles.sh`) should prove it under the owner/app split. The Postgres image contrib set was not inspected.
  - The plan says the violation maps "through `api.errors.DB_GUARD_CODES`". That is wrong for an exclusion constraint: `DB_GUARD_CODES` maps trigger messages of the form `CODE: ...` and a test checks it equals the codes raised in `pg_proc` (`backend/api/tests/test_db_guard_errors.py:45-46`). An exclusion violation is an `IntegrityError` (SQLSTATE 23P01) that today becomes a generic `409 CONFLICT` (`backend/api/errors.py:247-251`). The service must catch it and raise `APPOINTMENT_CONFLICT`.
  - The constraint WHERE clause names `requested`, so `REQUESTED` and the constraint belong in one migration (the plan puts the status in Phase 4 but the constraint in Phase 3; see section 4, contradiction 2). `choice_check("status", ...)` (`models.py:270`) must also change.
  - `pghistory` tracks `Appointment` (`@track_history()`, `models.py:217`); the event table copies columns but not constraints, so the constraint does not touch it.

**Verdict:** safe, provided the migration pre-checks and reports conflicts. No product change to staff booking is needed because overbooking is not a feature today. If reception wants an "urgent double-book", that would be a new, audited override and would conflict with this constraint; ask the owner once (section 7, still open item 1).

### (b) Permission guarding the center page, and the migration for `core.manage_public_site`

**Findings.**
- Today every center page endpoint requires `core.manage_settings`: `core_get_center_page`,
  `core_update_center_page`, `core_list_announcements`, `core_create_announcement`,
  `core_update_announcement` (`backend/apps/core/api.py:410-470`), and the admin screen's nav entry
  (`frontend/src/features/admin/sections.ts:70-75`, permission `core.manage_settings`). The same
  code also guards the center profile, logo, policy and sequences (`api.py:347-381`, `:684`)
  and the design guide link (`frontend/src/components/AppShell.tsx:422`).
- The code is registered with default roles `{admin, manager}` (`backend/apps/core/permissions.py:164-169`).
  Role grants are the registry default **plus `RolePermission` override rows** (`apps/core/models.py:145-160`;
  `effective_permissions` / `role_permissions`, `permissions.py:99-131`). An administrator can grant
  `core.manage_settings` to any role from the matrix; the test
  `backend/apps/core/tests/test_admin_api.py:296-319` does exactly that for the receptionist, and
  reverting to the default **deletes** the override row.
- **Consequence for the migration.** If `core.manage_public_site` were simply registered with
  default roles `{admin, manager}`, then: (1) a role the administrator had granted
  `core.manage_settings` (an override row) would silently lose the ability to edit the center page;
  (2) a default role whose `core.manage_settings` had been denied by an override would silently
  gain the new code. Both are regressions in who can edit a public page.
- **Required data migration (ADR 0029, decision B; reviewer recommendation 5).** In `core`,
  after the code is registered: for each role compute the effective `core.manage_settings` (the
  default set `{admin, manager}` overridden by that role's `RolePermission` row, if any); the
  desired `core.manage_public_site` for the role equals it; write a `RolePermission` row for
  `core.manage_public_site` **only where the desired value differs from the new code's default**
  (so an extra granted role gets `allowed=True`, a default role that was denied gets
  `allowed=False`, and untouched roles get nothing, matching how the matrix stores overrides).
  Superusers hold every registered code (`permissions.py:108-109`) and need nothing. The migration
  must hard-code the two default roles (a historical migration should not import the live
  registry) and be idempotent. Reverse: delete the rows it wrote.
- The plan contradicts itself here (contradiction 3): D4 says the settings row is edited by
  `core.manage_settings`; section 2 says `core.manage_public_site` is separate "so a marketing
  person can edit the site without touching policy". ADR 0029 follows section 2.
- Also affected: the permission matrix lists every registered code, so the new codes appear
  there; `frontend/src/features/admin/sections.ts` and `nav-permissions.test.ts:64`; the
  notification kinds table needs a link permission for `online_booking_requested`
  (`visits.manage_online_bookings`), and the contract test that parses it
  (`backend/apps/core/tests/test_notification_kinds.py`, `frontend/src/features/notifications/kinds.ts`).

### (c) Root `/` routing: `MARKETING_SITE` versus the center website

**What happens today** (`frontend/src/app/routes.tsx:57-80`): the `_app` route's `beforeLoad`
runs only for the exact path `/`; if `isMarketingSite()` (from `GET /api/ops/site`, read once before
first render, `frontend/src/lib/site.ts`) and there is **no staff session**, it returns
`marketingRoot: true` and `AppEntry` renders the lazy vendor sales page. Otherwise it requires a
staff user (`requireAppUser`, `frontend/src/app/guards.ts`) and renders the app shell, so a
signed-out visitor with marketing off is redirected to `signInPath()` (`/login`). `/portal` is a
different route tree (`frontend/src/portal/routes.tsx`) whose index is the center page (ADR 0023).
`/login` is the sales page while `MARKETING_SITE=1` and the staff sign-in otherwise; `/sign-in` is
always the staff sign-in (ADR 0027). So **there is no collision today**: the vendor page owns `/`
and `/login` when its flag is on, and the center page owns `/portal`.

**What breaks once the center has a website.** The user's rule is "the center website wins at `/`
when `site_enabled`". That needs the SPA to know `site_enabled` before first render for a visitor
with no session, and a precedence between two public pages at one path. ADR 0028 decision 4 fixes
the order (staff session, then center site, then vendor page, then sign-in) and extends
`GET /api/ops/site` with `center_site`. Consequences:
- `frontend/src/lib/site.ts` (`SiteConfig`, `loadSiteConfig`), `frontend/src/lib/site.test.ts`,
  `frontend/src/app/routes.tsx` (`beforeLoad`, `AppEntry`), `backend/apps/ops/{api,schemas,services}.py`,
  `backend/apps/ops/tests/test_contract.py:17,35` change.
- `signInPath()` must keep using `marketing` only (the sales page lives at `/login`); a center
  website at `/` is not at `/login`, so `signInPath()` is unchanged. A "Staff sign-in" link on the
  center site goes through it.
- `frontend/public/robots.txt` allows `/` and `/login` (ADR 0027): with a center site at `/`
  the center's own SEO is served; no change needed, but note it.
- The OVH production deployment has `MARKETING_SITE=1` and an empty center profile (project
  memory, 2026-10-29; **not re-read from the server**). Nothing changes there until an
  administrator switches `site_enabled` on, and then `/` becomes the center site while `/login`
  keeps the sales page. The owner should know that a vendor demo host would stop showing its sales
  page at `/` as soon as its demo center enables its site.
- e2e: `e2e/tests/marketing/marketing.spec.ts` (intercepts `/api/ops/site`, asserts root behavior),
  `e2e/tests/portal/center-page.spec.ts`, `e2e/tests/auth.spec.ts` and the route registry
  (`e2e/routes.ts`) gain the `/` states; the responsive matrix must run the center site at `/`.

## 3. Verified facts the later phases depend on (beyond the plan)

1. **Statuses are read as `BOOKED` in many places** and every one must decide whether `REQUESTED`
   counts: `backend/apps/visits/services.py:309` (`create_visit` from an appointment),
   `:686` (`_check_slot`), `:744` (`_booked`, used by reschedule, cancel, no-show),
   `:847` (`available_slots`), `:1439` (merge moves future appointments), `:1942` (`_HOLDS_SLOT`,
   day view), `:2062` (`upcoming_appointments`), `backend/apps/portal/queries.py:120,142`,
   `backend/apps/portal/services.py:612,652` (open count, cancel), `backend/apps/core/demo/activity.py:1033`,
   and the schema literal `AppointmentStatusCode` `backend/apps/visits/schemas.py:25` (which becomes
   a generated frontend type). Missing one means a held slot that cannot be listed, cancelled or
   counted against `max_open`.
2. **Maintenance runs hourly, not daily** (`infra/docker-compose.yml`, service `maintenance`),
   so request expiry cannot rely on it alone; ADR 0029 adds lazy expiry under the doctor lock.
3. **`PortalEvent.kind` is `max_length=20`** (`backend/apps/portal/models.py:187`) and the plan's
   `guest_booking_created` is 21 characters; `PortalThrottle.scope` is `max_length=10`
   (`models.py:137` region) and `guest_phone` is 11. Both columns need a widening migration (the
   `portal_event` append-only trigger blocks UPDATE/DELETE, not ALTER; **to be confirmed on a real
   database in Phase 4**).
4. **`visits_appointmentevent` is append-only by trigger** (`backend/apps/visits/migrations/0001_initial.py`),
   so a retention purge cannot erase a guest's name and phone from history (ADR 0029 decision G
   states this).
5. **Staff-session operations live in the portal router**: `POST /api/portal/access-codes`,
   `GET|POST /api/portal/patients/{id}/access-codes`, `POST /api/portal/access-codes/{id}/revoke`
   (`backend/apps/portal/api.py:232-330`, `auth=session_auth`). A path rule `/api/portal/*` at an
   edge would expose them to the internet (they still need a staff cookie, but they should not be
   reachable at all). The LAN edge of ADR 0028 (decision 3, Phase 6) allowlists exact paths; on an
   internet-facing deployment they stay reachable on the one host and are protected by
   `session_auth` and their permission, like every staff route.
6. **CSRF for public POSTs** comes from `GET /api/auth/csrf` today (`frontend/src/lib/api/csrf.ts`,
   `frontend/src/portal/api.ts:53`), so an edge that refuses `/api/auth/*` (the plan's list) would
   break every public POST. The LAN edge of ADR 0028 lists `GET /api/auth/csrf` as an exact path;
   an internet-facing deployment serves it as today.
7. **Client address behind proxies**: `client_ip` trusts the leftmost `X-Forwarded-For` only when
   `DJANGO_TRUST_X_FORWARDED_FOR=1` (`backend/apps/core/services.py:96-106`,
   `backend/config/settings.py:223`). The per-address limits that guest booking relies on are only
   as good as the proxy configuration (ADR 0028 decision 6). The OVH host Caddy was not read.
8. **Path names in the plan do not match the code**: the plan writes `/booking/doctors...`; the
   code has `/api/portal/doctors`, `/doctors/{id}/days`, `/doctors/{id}/slots`
   (`backend/apps/portal/api.py:399-430`).
9. **Phone normalization exists**: `domain.center_page.whatsapp_number` folds Arabic digits and Sudanese
   local numbers to `249...` (`backend/domain/center_page.py:147-170`), enough for the `wa.me`
   buttons; phones stored on appointments are free text (`contact_phone`, 30 chars), so the
   per-phone cap needs a normalized comparison (`domain.portal.phones_match` is the nearest helper,
   `backend/domain/portal.py:103`).

## 4. Contradictions and gaps in the plan

1. **Request expiry** (D3 `min(starts_at - lead, created + N, setting)` versus section 7.8 "24
   hours before the slot"). Resolved by the owner: `expires_at = min(created_at + request_ttl_hours,
   starts_at - lead)`. ADR 0029 A8. A request created less than the minimum review window before its
   cap would be born expired; ADR 0029 adds a 30-minute floor (proposed).
2. **Phase order for `REQUESTED`.** Section 3 puts the status in the `visits` migration, Phase 3
   adds the exclusion constraint whose WHERE names `requested`, and Phase 4 introduces the flow.
   The status value and the constraint must land together (Phase 3).
3. **Who edits the site settings:** D4 (`core.manage_settings`) versus section 2
   (`core.manage_public_site`, "separate"). Resolved to the latter, with the grant-preserving
   migration of finding (b).
4. **Data model:** section 3 puts `guest_access` on `Appointment` *and* `appointment 1:1` on
   `GuestBookingAccess`: two owners of one link. Also a 1:1 to one appointment row breaks when a
   guest reschedules (the old row becomes `rescheduled`, a new row is created). ADR 0029 D: the
   access belongs to the chain and is moved in the same transaction.
5. **Edge allowlist** `/api/portal/*` includes staff-session operations (fact 5) and omits the CSRF
   endpoint (fact 6). Exact-path allowlist for the LAN edge in ADR 0028 decision 3 (Phase 6 only).
6. **Exclusion violation mapping** through `DB_GUARD_CODES` does not work (finding a).
7. **Approval default changes existing behavior.** Decision 2 applies "every online booking" to
   registered patients too, so after Phase 4 an install that already uses portal booking
   (instant `booked` today, `backend/apps/portal/tests/test_booking.py:81`) would start asking
   reception to approve. **Decided 2026-10-29:** the Phase 1 migration seeds `require_approval`
   off on an existing install (at least one `patients.Patient` row when it runs) and on on a new
   install (ADR 0029 K1).
8. **Topology wording.** Section 7.1 says the feature works on a plain internet-facing deployment;
   plan D1 and Phase 6 describe only the tunnel. **Decided 2026-10-29:** one domain, one host, one
   process; no public listener; security from app-level enforcement (ADR 0028 decision 3). The
   tunnel and its exact-path allowlist are Phase 6, for LAN installs only.
9. **Maintenance cadence:** the plan says `maintenance` expires requests; it is hourly (fact 2).
10. **`seed_e2e` / `seed_demo`** must fill the new settings and content (ADR 0023 did the same);
    not mentioned in the plan.
11. **Phase 6 sequence:** `infra/edge` is listed last, but the `ops/site` change (finding c) is
    Phase 1 work; moved there in section 6. With no public listener (ADR 0028 decision 3), Phase 1
    has no infrastructure change at all.

## 5. Existing tests that must change

Grouped by the phase that changes them. "Add" means a new case in an existing file; "update"
means an existing assertion is wrong after the change. Counts are not given: they come from the
real run in each phase.

**Phase 1 (switches, `center-identity`, `ops/site`; no public listener)**
- `backend/api/tests/test_main.py:145` (pinned operation ids), `:190-210` (public operation set),
  `:223-259` (`OPEN_OPERATIONS` allowlist): add the new public operations.
- `backend/api/tests/test_permission_sweep.py:44-58` (`PUBLIC`), `:149` (what an anonymous client
  reaches).
- `backend/apps/core/tests/test_display_role.py:42-49` (operations the kiosk account may call).
- `backend/apps/portal/tests/test_contract.py:19-20` (portal operation list),
  `backend/apps/ops/tests/test_contract.py:17,35` (`ops_get_site` shape).
- `backend/apps/portal/tests/test_center_page.py:127-141` (pinned public field set), and new switch
  tests for every public and patient endpoint with each switch off.
- `backend/apps/core/tests/test_permissions.py:20-26` (`CORE_CODES`), `:133`, `:233` (role
  defaults), `backend/apps/core/tests/test_admin_api.py:675-690` (permission per endpoint table:
  center page and announcements move to `core.manage_public_site`), `:296-319` (matrix), and
  `backend/apps/core/tests/test_center_page_api.py:2,187` (`test_needs_manage_settings`).
- `backend/apps/core/tests/test_schema.py:50-60` (untracked-model allowlist, updated deliberately),
  and the migration test for the grant-preserving permission data migration (new).
- `backend/apps/core/tests/test_seeds.py` / `test_e2e_seed.py` (seeds fill the new row).
- Frontend: `frontend/src/lib/site.test.ts`, `frontend/src/app/routes.test.ts` (root `/`),
  `frontend/src/app/nav-permissions.test.ts:64`, admin section tests, the i18n key-parity tests,
  `frontend/src/lib/api/schema.d.ts` and `frontend/openapi.json` (regenerated, drift check).
- e2e: `e2e/routes.ts`, `e2e/module-routes/portal.ts` (new routes enter the responsive matrix),
  `e2e/tests/marketing/marketing.spec.ts`, `e2e/tests/portal/center-page.spec.ts`,
  `e2e/tests/auth.spec.ts`, `scripts/e2e.sh` (rate-limit variables for the new public routes).

**Phase 2 (website content)**
- `backend/apps/portal/tests/test_center_page.py` (pinned fields grow; hidden/empty rendering),
  `backend/apps/core/tests/test_center_page_api.py`, `backend/apps/core/tests/test_schema.py`
  (pghistory tracking of `CenterMedia`, `CenterFaq`, `Testimonial`), `domain` tests for new rules.
- `e2e/tests/portal/center-page.spec.ts` (full/sparse/empty variants), axe check.

**Phase 3 (availability)**
- `backend/apps/visits/tests/test_models.py:66-72` (constraint tests; add the exclusion case),
  `backend/apps/visits/tests/test_services.py:630` (concurrent booking: extend to the 8-thread,
  real-Postgres version and a direct-SQL overlap case), `test_board.py`, `test_review_fixes.py`,
  `test_api.py`, `test_contract.py` (operation ids).
- `backend/apps/portal/tests/test_booking.py` (slots exclude time off and `requested`; reschedule),
  `backend/domain/tests/test_portal.py` (`check_reschedule`, Hypothesis over schedules x time off x bookings).
- `backend/api/tests/test_db_guard_errors.py` stays as is (the exclusion violation is not a trigger
  code); add a case that the service maps it to `APPOINTMENT_CONFLICT`.
- `infra/tests/test_db_roles.sh` (create `btree_gist` as the owner, app role has no DDL),
  `infra/tests/` restore drill (the drill's `integrity_check`).
- Frontend: `AppointmentStatusCode` consumers in `frontend/src/features/visits/`; e2e appointment specs.

**Phase 4 (guest booking and inbox)**
- `backend/apps/portal/tests/test_booking.py:60,81,187` (status after booking is `requested` when
  approval is on; open-count includes `requested`), `test_access.py` (three-way session matrix),
  `test_auth.py`, `test_housekeeping.py` (purge, expiry, retention), `test_models.py` (new tables),
  `test_contract.py`.
- `backend/api/tests/test_main.py`, `test_permission_sweep.py` (new operations and permission
  `visits.manage_online_bookings`), `backend/apps/core/tests/test_notification_kinds.py` and
  `frontend/src/features/notifications/kinds.ts` contract (two new kinds).
- `backend/apps/visits/tests/*` for every `BOOKED` filter listed in fact 1.
- `backend/apps/core/tests/test_permissions.py` (new codes).
- e2e: `e2e/tests/portal/booking.spec.ts`, `own-data.spec.ts`, `sign-in.spec.ts`,
  `e2e/tests/followups/portal-codes.spec.ts`, `e2e/tests/cycle/full-cycle.spec.ts` (if it books
  online), route registry for `/portal/book`, `/portal/booking`, the inbox.

**Phase 5 (tracking)**
- `backend/apps/portal/tests/test_access.py` (cross-patient 404 for timeline and notices),
  `backend/apps/lab/tests/*` (approval writes a notice in the same transaction), new
  `backend/domain/tests/test_portal_status.py`; e2e `own-data.spec.ts`, `home.spec.ts`.

**Phase 6 (edge, LAN installs only)**
- `infra/tests/run.sh` gains the edge-config case (refuses `/api/auth/*`, staff routers, `/admin`,
  `/sign-in`, the staff-session portal operations); runbook and guide pages.

## 6. Release trains (replaces plan section 6)

Phases keep their numbers and content; they are grouped so that something useful and safe reaches
production at each stop, and so that the owner sees real behavior before the risky part.

| Train | Phases | What the owner gets | Why it stops there |
|---|---|---|---|
| **A** | 1, 2, 3 | Switches and their enforcement; the full center website; availability hardening (time off, `online_bookable`, exclusion constraint, `requested` support, portal reschedule). Booking behaves as today (registered patients only, instant) until train B because nothing creates `requested` rows yet. | Ships the website and fixes double-booking risk with no new public write path. Everything stays off by default. The migration risk (constraint, permission data migration) is exercised on the demo first. |
| **B** | 4 | Guest booking, approval by reception, the inbox, abuse limits, the `wa.me` buttons, retention. `require_approval` takes effect for registered patients too (on for new installs; existing installs were seeded off in Phase 1). | The first anonymous write path. |
| **C** | 5 | Patient tracking: visit timeline, status mapping, notices. | Read-only on existing data; independent of B. |
| (LAN only) | 6 | Edge, tunnel, runbook, guides. | Only for centers without a public server; an internet-facing deployment (OVH) skips it. |

Dependencies to respect: the `ops/site` change is in train A (Phase 1), not Phase 6 as the plan's
order implied; there is no public listener in any phase (ADR 0028 decision 3); `REQUESTED` and the constraint ship together in Phase 3
(train A); the guides (reception inbox, administrator) ship with the phase that adds the screens,
and Phase 6 only adds the edge runbook. Each phase still ships with `ship-feature` and is its own PR.

## 7. Owner decisions and remaining open items

### Decided by the owner on 2026-10-29 (binding)

1. **Topology:** the center website, booking, the patient portal and the staff app stay under
   **one** domain on **one** host (for example `healtfull.stingdev.pro` serves everything). No
   separate public hostname, no separate public listener, no network isolation on the OVH
   deployment. Security comes from app-level enforcement (switches, authentication separation,
   throttles). The exact-path allowlist survives only as the optional edge configuration for LAN
   installs (Phase 6). ADR 0028 decision 3.
2. **Existing installs and approval:** `require_approval` is on for a new install; the Phase 1
   migration seeds it off for an existing install, detected as "the `patients.Patient` table holds
   at least one row when the migration runs" (the migration depends on the latest `patients`
   migration; a fresh install migrates an empty database before any seed). Registered patients
   keep booking instantly until the administrator turns approval on. ADR 0029 K1.
3. **Guest data retention:** the anonymize-in-place purge leaves earlier copies of a guest's name
   and phone in the append-only appointment history. Accepted and documented. ADR 0029 G, K3.
4. **Defaults accepted, all editable by the administrator in the settings row:** pending requests
   per doctor per day 10, requests per address per day 5, proof-of-work 18 bits, guest retention 90
   days, minimum review window 30 minutes. ADR 0029 K4.

### Still open

1. **Urgent double-booking:** is there any real need for staff to overbook a slot? If yes, it needs a
   separate audited override and a different constraint design; if no, nothing changes. Needed
   before Phase 3.
2. **Tunnel provider** for LAN installs (WireGuard to a vendor VPS recommended; a managed tunnel is
   the alternative). Needed before Phase 6.
3. **Not verified (no server access, by instruction):** the OVH host Caddy and compose Caddy
   forwarding headers (ADR 0028 decision 6, to check before the public switches go on at OVH);
   whether production or demo data contains overlapping booked appointments; the `portal_event`
   trigger's behavior on ALTER; contrib extensions in the Postgres image.
