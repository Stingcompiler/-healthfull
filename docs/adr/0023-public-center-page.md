# 0023: A public center page in the patient portal, with fixed sections

Date: 2026-10-24. Status: accepted. Extends 0016 (portal) without changing its rules.

## Context
Patients reach the portal from the address printed on a receipt or a reception slip. Before
signing in they saw only a form. The center wanted a public page there: who the center is,
when it is open, its doctors and clinic days, notices (holiday closures), and how to reach
it. The user chose a page inside the portal kept from a settings screen with fixed sections,
not a page builder and not a separate website.

## Decisions
- **Where.** `/portal` is the center page; the patient sign-in moved to `/portal/sign-in`
  (expired and signed-out sessions return there). The page works with or without a portal
  session; signed in, its action opens the file instead.
- **Data.** Identity, address and the main phone stay in `CenterProfile`. A new singleton
  `CenterPage` holds only what has no other home: a short text, weekly opening hours, a
  WhatsApp number (stored as international digits), an e-mail, directions, one visibility
  switch per section, and the ids of departments and doctors kept off the page.
  `Announcement` rows (bilingual title and text, first and last day, active, order) are shown
  while active and inside their dates. Departments, doctors and clinic days are read from
  `Department`, `DoctorProfile` and the current `DoctorSchedule` rows that booking uses: never
  entered twice. A hidden department hides its doctors. Rules in `domain/center_page.py`
  (hours, today's status, announcement window, WhatsApp and `tel:` links), Hypothesis-tested.
- **Who edits.** `core.manage_settings`, like the center profile; every change is tracked by
  pghistory with the user and a reason (`center page`, `create announcement`, ...).
- **Public endpoints.** `GET /api/portal/center-page` and `GET /api/portal/center-logo`, no
  session. The answer has a pinned set of fields (tested): never prices, registration or tax
  numbers, or staff other than the doctors shown. Hidden or empty sections come back empty and
  the page leaves them out. Each read counts against the client address
  (`PORTAL_PAGE_IP_MAX`, default 300 per `PORTAL_PAGE_IP_WINDOW_SECONDS` = 600, then
  `429 RATE_LIMITED` and a `page_throttled` PortalEvent), like the receipt check. The page
  answer is `no-store` like every portal answer; the logo, whose URL carries its version, may be
  cached for an hour. The staff sign-in page reads the same endpoint for the center's name and
  logo (public data, no session).
- **No internet.** No map embed and no fetch of any external URL. The `tel:`, `mailto:` and
  `https://wa.me/<digits>` links are plain links the visitor's phone opens.
- **Not built.** A price display switch (prices stay off the page); overnight opening spans.

## Consequences
- `scripts/e2e.sh` raises `PORTAL_PAGE_IP_MAX`: every spec opens a sign-in page from 127.0.0.1.
- Printed slips keep their `/portal` address; the patient taps "Sign in to your file" once more.
- `seed_e2e` and `seed_demo` fill the page once (an edited page is left as it is).

## Code
`domain/center_page.py`, `apps/core/{models,services,schemas,api}.py` (core migration 0017),
`apps/portal/{api,queries,services,schemas,conf}.py` (portal migration 0005),
`apps/core/e2e/center_page.py`; frontend `src/lib/center/`, `src/components/CenterIdentity.tsx`,
`src/portal/pages/CenterPage.tsx`, `src/features/admin/pages/CenterPageSettingsPage.tsx`;
e2e `e2e/tests/portal/center-page.spec.ts`.
