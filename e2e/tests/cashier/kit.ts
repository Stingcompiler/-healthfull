/**
 * Shared steps of the cashier specs: a logged-in page per seed user (English UI, so the specs
 * read the en texts through `tr`), the 70% payer, and a clean shift state for a cashier.
 */
import { expect, type Browser, type Locator, type Page } from "@playwright/test";

import { closeShift, fixture, login, openShift, setPrefs, tr } from "../../helpers";
import type { SeedUser } from "../../fixtures/users";

export const LANG = "en" as const;

/** `t("cashier:payment.submit")` in the language the cashier specs use. */
export function t(key: string, vars: Record<string, string> = {}): string {
  return tr(LANG, key, vars);
}

/** A fresh browser context logged in as `who`, light theme, English. */
export async function pageAs(browser: Browser, who: SeedUser): Promise<Page> {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  await login(page, who);
  await setPrefs(page, { theme: "light", lang: LANG });
  return page;
}

/** The payer that pays 70% of cash prices (backend apps/payments/e2e_fixtures.py). */
export async function payer70(): Promise<string> {
  const { payer } = await fixture<{ payer: string }>("cashier_payer", {});
  return payer;
}

/** Leaves `who` with no open shift (closes one at its expected cash). */
export async function noShift(who: SeedUser = "cashier"): Promise<void> {
  await openShift({ as: who, if_open: "close" });
  await closeShift({ as: who });
}

/** Opens the desk on a visit: search by file number, pick the visit. */
export async function openVisit(page: Page, fileNo: string, visitNumber: string): Promise<void> {
  await page.goto("/cashier");
  const search = page.getByTestId("cashier-lookup");
  await search.fill(fileNo);
  const visit = page.locator(`[data-testid="lookup-visit"][data-visit-number="${visitNumber}"]`);
  await expect(visit).toBeVisible();
  await visit.click();
  await expect(page.getByTestId("visit-number")).toHaveText(visitNumber);
}

/** The table row (or card) of an invoice line whose service name contains `service`. */
export function lineRow(scope: Locator, service: string): Locator {
  return scope.locator("tr, [data-testid=invoice-line]").filter({ hasText: service });
}

/** Picks an option of a shared SelectField by its label text. */
export async function choose(page: Page, label: string, option: string): Promise<void> {
  await page.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

/** Money as the en UI shows it inside a MoneyText ("SDG 3,000.00"). */
export function sdg(amount: string): RegExp {
  const [int = "0", frac = "00"] = amount.split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return new RegExp(`${grouped.replace(/,/g, ",")}\\.${frac}`);
}
