/**
 * Shared steps of the claims specs: a logged-in page per seed user (English UI, so the specs
 * read the en texts through `t`), one payer's case at a chosen claim stage (backend fixture
 * `claims_case`, a new payer each call), row actions, and a minimal reader for the exported
 * .xlsx (a zip of XML parts).
 */
import { inflateRawSync } from "node:zlib";

import { expect, type Browser, type Locator, type Page } from "@playwright/test";

import { fixture, login, setPrefs, tr } from "../../helpers";
import type { SeedUser } from "../../fixtures/users";

export const LANG = "en" as const;

/** `t("claims:detail.submit")` in the language the claims specs use. */
export function t(key: string, vars: Record<string, string> = {}): string {
  return tr(LANG, key, vars);
}

/** A fresh browser context logged in as `who`, light theme, English. */
export async function pageAs(browser: Browser, who: SeedUser, width = 1280): Promise<Page> {
  const context = await browser.newContext({
    viewport: { width, height: 900 },
    acceptDownloads: true,
  });
  const page = await context.newPage();
  await login(page, who);
  await setPrefs(page, { theme: "light", lang: LANG });
  return page;
}

export interface ClaimCase {
  payer: { id: number; code: string; name_en: string };
  patient: { id: number; file_no: string; full_name_en: string };
  visit: { id: number; number: string };
  invoice: { id: number; number: string };
  claim: {
    id: number;
    number: string;
    status: string;
    lines: { id: number; amount: string }[];
  } | null;
}

/** A new 70% payer's approved invoice of `services`, taken to `stage` (apps/claims/e2e_fixtures.py). */
export function claimCase(params: {
  stage?: "accrued" | "draft" | "submitted" | "answered";
  services?: string[];
  outcomes?: ("accepted" | "partial" | "rejected")[];
}): Promise<ClaimCase> {
  return fixture<ClaimCase>("claims_case", params);
}

/** Opens the row actions menu of `row` and picks `action`. */
export async function rowAction(page: Page, row: Locator, action: string): Promise<void> {
  await row.getByRole("button", { name: tr(LANG, "table.rowActions") }).click();
  await page.getByRole("menuitem", { name: action }).click();
}

/** Picks an option of a shared SelectField by its label text. */
export async function choose(page: Page, label: string, option: string): Promise<void> {
  await page.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

/** Money as the en UI shows it inside a MoneyText ("15,400.00"). */
export function sdg(amount: string): RegExp {
  const [int = "0", frac = "00"] = amount.split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return new RegExp(`${grouped}\\.${frac}`);
}

/** The entries of a zip file (local headers; openpyxl writes sizes there), inflated. */
export function unzip(bytes: Buffer): Map<string, string> {
  const out = new Map<string, string>();
  let at = 0;
  while (at + 30 <= bytes.length && bytes.readUInt32LE(at) === 0x04034b50) {
    const method = bytes.readUInt16LE(at + 8);
    const size = bytes.readUInt32LE(at + 18);
    const nameLength = bytes.readUInt16LE(at + 26);
    const extraLength = bytes.readUInt16LE(at + 28);
    const name = bytes.subarray(at + 30, at + 30 + nameLength).toString("utf8");
    const start = at + 30 + nameLength + extraLength;
    const data = bytes.subarray(start, start + size);
    out.set(name, (method === 8 ? inflateRawSync(data) : data).toString("utf8"));
    at = start + size;
  }
  return out;
}

/** The claim detail page is loaded (its totals and at least one line). */
export async function claimLoaded(page: Page): Promise<void> {
  await expect(page.getByTestId("claim-totals")).toBeVisible();
}
