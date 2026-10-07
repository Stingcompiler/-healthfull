/**
 * Contract guard: every permission code the navigation (and the
 * administration sections) checks is a real backend code, registered with
 * `register_permission("<app>.<action>", ...)` in backend/apps/<app>/permissions.py
 * (ARCHITECTURE 4.10).
 *
 * Phase 0 registers only core.* and ops.*. Codes owned by modules built in
 * later phases are listed in PENDING below with the phase that registers them.
 * When a backend app registers one, this test fails until the code is removed
 * from PENDING, so a typo on either side cannot hide a menu entry for good.
 */
import { describe, expect, it } from "vitest";

import { ADMIN_SECTIONS } from "@/features/admin/sections";

import { ALL_NAV } from "./nav";

const sources = import.meta.glob<string>(["../../../backend/apps/**/permissions.py", "!../../../backend/**/tests/**"], {
  query: "?raw",
  import: "default",
  eager: true,
});

/** Codes the UI already uses whose backend app arrives in a later phase (docs/PROMPT.md phases). */
const PENDING: Readonly<Record<string, string>> = {
  "patients.view": "Phase 2 (patients)",
  "visits.view_queue": "Phase 2 (visits)",
  "visits.manage_appointments": "Phase 2 (visits)",
  "clinical.view": "Phase 3 (clinical)",
  "orders.perform_procedure": "Phase 5 (orders/procedures)",
  "payments.take_payment": "Phase 4 (payments)",
  "pharmacy.dispense": "Phase 5 (pharmacy)",
  "lab.view_worklist": "Phase 5 (lab)",
  "claims.view": "Phase 6 (claims)",
  "reports.view": "Phase 6 (reports)",
  "catalog.manage": "Phase 1 (catalog)",
  "catalog.manage_prices": "Phase 1 (catalog)",
  "catalog.manage_payers": "Phase 1 (catalog)",
  "imports.run": "Phase 6 (imports)",
};

const CODE_SHAPE = /^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$/;

function registeredCodes(): Set<string> {
  const codes = new Set<string>();
  const pattern = /\bregister_permission\(\s*"([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)"/g;
  for (const text of Object.values(sources)) {
    for (const match of text.matchAll(pattern)) {
      if (match[1]) codes.add(match[1]);
    }
  }
  return codes;
}

function uiCodes(): Set<string> {
  const codes = new Set<string>();
  for (const item of ALL_NAV) {
    if (item.permission === undefined) continue;
    for (const code of typeof item.permission === "string" ? [item.permission] : item.permission) codes.add(code);
  }
  for (const section of ADMIN_SECTIONS) codes.add(section.permission);
  return codes;
}

const hasBackend = Object.keys(sources).length > 0;

describe.skipIf(!hasBackend)("navigation permission codes", () => {
  const registered = registeredCodes();
  const used = uiCodes();

  it("finds the backend registry (the scan itself works)", () => {
    for (const code of ["core.manage_users", "core.manage_settings", "ops.view_status"]) {
      expect(registered.has(code), code).toBe(true);
    }
  });

  it("are all well-formed <app>.<action> codes", () => {
    expect([...used].filter((code) => !CODE_SHAPE.test(code))).toEqual([]);
  });

  it("are registered by the backend or listed as pending for a later phase", () => {
    const unknown = [...used].filter((code) => !registered.has(code) && !(code in PENDING));
    expect(unknown, "register these in backend/apps/<app>/permissions.py (or fix the typo)").toEqual([]);
  });

  it("lists no pending code that the backend now registers", () => {
    const done = Object.keys(PENDING).filter((code) => registered.has(code));
    expect(done, "remove these from PENDING in src/app/nav-permissions.test.ts").toEqual([]);
  });

  it("lists no pending code the UI no longer uses", () => {
    const stale = Object.keys(PENDING).filter((code) => !used.has(code));
    expect(stale, "remove these from PENDING in src/app/nav-permissions.test.ts").toEqual([]);
  });
});
