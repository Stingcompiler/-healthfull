/**
 * Shared steps of the portal specs and screens: patients built by the backend fixture
 * `portal_patient` (apps/portal/e2e_fixtures.py, one call each), signing in to the portal
 * through its API (the portal cookie is not the staff session), and a phone-sized page.
 */
import { expect, type Browser, type Page } from "@playwright/test";

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
