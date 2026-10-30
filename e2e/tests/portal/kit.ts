/**
 * Shared steps of the portal specs and screens: patients built by the backend fixture
 * `portal_patient` (apps/portal/e2e_fixtures.py, one call each), signing in to the portal
 * through its API (the portal cookie is not the staff session), and a phone-sized page.
 */
import { createHash, randomUUID } from "node:crypto";

import { expect, type APIRequestContext, type Browser, type Page } from "@playwright/test";

import { csrfHeaders, fixture, setPrefs, tr } from "../../helpers";

export const LANG = "en" as const;

export function t(key: string, vars: Record<string, string> = {}): string {
  return tr(LANG, key, vars);
}

export interface PortalPatient {
  patient: { id: number; file_no: string; phone: string };
  visit: { id: number; number: string };
  approved_line: number;
  draft_line: number;
  invoice: { id: number; number: string };
  payment: { id: number; number: string };
  verify_token: string;
  code: string | null;
  appointment: { id: number; starts_at: string } | null;
}

/** A new patient with everything the portal shows (see the fixture's docstring). */
export function portalPatient(params: { appointment?: boolean; code?: boolean } = {}): Promise<PortalPatient> {
  return fixture<PortalPatient>("portal_patient", params);
}

let screens: Promise<PortalPatient> | undefined;

/** The patient behind the responsive screens, built once per worker. */
export function screensPatient(): Promise<PortalPatient> {
  screens ??= portalPatient({ appointment: true });
  screens.catch(() => {
    screens = undefined;
  });
  return screens;
}

/** Signs the page's browser context in to the portal (sets the portal cookie). */
export async function signInPortal(page: Page, who: PortalPatient, code = who.code): Promise<void> {
  const context = page.context();
  const response = await context.request.post("/api/portal/session", {
    headers: await csrfHeaders(context),
    data: { file_no: who.patient.file_no, phone: who.patient.phone, code },
  });
  expect(response.status(), `portal sign-in: ${await response.text()}`).toBe(200);
}

/** A fresh phone-sized context (no staff session), English, light; window.print is a no-op. */
export async function phonePage(browser: Browser, width = 375): Promise<Page> {
  const context = await browser.newContext({ viewport: { width, height: 812 } });
  await context.addInitScript(() => {
    window.print = () => undefined;
  });
  const page = await context.newPage();
  await setPrefs(page, { theme: "light", lang: LANG });
  return page;
}

/** Fills the portal sign-in form and submits it. */
export async function fillSignIn(page: Page, fileNo: string, phone: string, code: string): Promise<void> {
  const form = page.getByTestId("portal-login");
  await form.getByLabel(t("portal:login.fileNo")).fill(fileNo);
  await form.getByLabel(t("portal:login.phone")).fill(phone);
  await form.getByLabel(t("portal:login.code")).fill(code);
  await form.getByRole("button", { name: t("portal:login.submit") }).click();
}

// --- Guest booking (ADR 0029 D, F; Phase 4) -------------------------------------------------

export interface GuestCreated {
  reference: string;
  pin: string | null;
  status: string;
  display_status: string;
  starts_at: string;
  share_url: string;
  replayed: boolean;
  doctor: { id: number; name_en: string };
}

/** A phone number no other spec uses (the per-phone cap counts open guest bookings). */
export function uniquePhone(): string {
  return `09${String(Math.floor(Math.random() * 1e8)).padStart(8, "0")}`;
}

/** The first nonce from 0 whose SHA-256(challenge + nonce) has `bits` leading zero bits. */
export function solvePow(challenge: string, bits: number): string {
  for (let n = 0; ; n++) {
    const digest = createHash("sha256").update(challenge + String(n)).digest();
    let zero = 0;
    for (const byte of digest) {
      if (byte === 0) {
        zero += 8;
        continue;
      }
      zero += Math.clz32(byte) - 24;
      break;
    }
    if (zero >= bits) return String(n);
  }
}

/**
 * Books a guest slot through the public API (as the booking page does: challenge, proof,
 * Idempotency-Key), on the doctor's furthest bookable day. Returns the answer and the key.
 */
export async function bookAsGuest(
  request: APIRequestContext,
  options: { name?: string; phone?: string; slot?: "first" | "last"; dayFromEnd?: number } = {},
): Promise<{ created: GuestCreated; key: string; body: Record<string, unknown> }> {
  const doctors = (await (await request.get("/api/portal/doctors")).json()) as { id: number }[];
  const doctor = doctors[0];
  if (!doctor) throw new Error("no doctor takes online bookings");
  const days = (await (await request.get(`/api/portal/doctors/${String(doctor.id)}/days`)).json()) as string[];
  const day = days.at(-(options.dayFromEnd ?? 1));
  if (!day) throw new Error("the doctor has no bookable day");
  const slots = (await (
    await request.get(`/api/portal/doctors/${String(doctor.id)}/slots?on=${day}`)
  ).json()) as { slots: { starts_at: string }[] };
  const slot = options.slot === "last" ? slots.slots.at(-1) : slots.slots[0];
  if (!slot) throw new Error("no free slot");
  const challenge = (await (await request.get("/api/portal/challenge")).json()) as { challenge: string; bits: number };
  const body = {
    doctor_id: doctor.id,
    starts_at: slot.starts_at,
    contact_name: options.name ?? "Guest Visitor",
    contact_phone: options.phone ?? uniquePhone(),
    challenge: challenge.challenge,
    nonce: solvePow(challenge.challenge, challenge.bits),
  };
  const key = randomUUID();
  const response = await request.post("/api/portal/guest-bookings", {
    headers: { ...(await csrfHeadersOf(request)), "Idempotency-Key": key },
    data: body,
  });
  expect(response.status(), `guest booking: ${await response.text()}`).toBe(201);
  return { created: (await response.json()) as GuestCreated, key, body };
}

async function csrfHeadersOf(request: APIRequestContext): Promise<Record<string, string>> {
  let token = (await request.storageState()).cookies.find((c) => c.name === "csrftoken")?.value;
  if (!token) {
    await request.get("/api/auth/csrf");
    token = (await request.storageState()).cookies.find((c) => c.name === "csrftoken")?.value;
  }
  return token ? { "X-CSRFToken": token } : {};
}
