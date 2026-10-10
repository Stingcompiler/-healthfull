/**
 * Shared steps of the pharmacy specs: a logged-in page per seed user (English UI, so the specs
 * read the en texts through `tr`), paid or unpaid prescriptions built through the cashier's
 * factories, and select helpers.
 */
import { expect, type Browser, type Locator, type Page } from "@playwright/test";

import { approveInvoice, createPatient, createVisit, login, orderLines, pay, setPrefs, tr } from "../../helpers";
import type { SeedUser } from "../../fixtures/users";

export const LANG = "en" as const;

/** `t("pharmacy:dispense.submit")` in the language the pharmacy specs use. */
export function t(key: string, vars: Record<string, string> = {}): string {
  return tr(LANG, key, vars);
}

/** A fresh browser context logged in as `who`, light theme, English. */
export async function pageAs(browser: Browser, who: SeedUser): Promise<Page> {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
  });
  const page = await context.newPage();
  await login(page, who);
  await setPrefs(page, { theme: "light", lang: LANG });
  return page;
}

/** A unique suffix for batch and invoice numbers (specs may run again on the same database). */
export function stamp(): string {
  return `${Date.now().toString(36)}${Math.floor(Math.random() * 1000).toString(36)}`.toUpperCase();
}

/** `today + days` as the yyyy-mm-dd a date input takes. */
export function dayFromNow(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${String(d.getFullYear())}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/**
 * A cash patient's visit with `quantity` units of `service` ordered by the doctor; invoiced
 * and paid in cash unless `paid` is false (then only invoiced). Returns the visit number.
 */
export async function prescription(service: string, quantity: number, paid = true): Promise<string> {
  const { patient } = await createPatient();
  const { visit } = await createVisit({ patient, coverage: "cash" });
  await orderLines({ visit, items: [{ service, quantity }] });
  const { invoice } = await approveInvoice({ visit, services: [service] });
  if (paid) await pay({ invoice });
  return visit.number;
}

/** Picks an option of a select (combobox) by its label text. */
export async function choose(scope: Page | Locator, label: string, option: string | RegExp): Promise<void> {
  const page = "page" in scope ? scope.page() : scope;
  await scope.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option }).first().click();
}

/** Opens the dispense dialog of a visit from the queue: type (or scan) its number, Enter. */
export async function openDispense(page: Page, visitNumber: string): Promise<Locator> {
  await page.goto("/pharmacy");
  const scan = page.getByTestId("queue-scan");
  await scan.fill(visitNumber);
  await scan.press("Enter");
  const dialog = page.getByTestId("dispense-dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByTestId("dispense-line").first()).toBeVisible();
  return dialog;
}
