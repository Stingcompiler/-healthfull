/**
 * Shared steps of the report specs: a logged-in English page per seed user, money matchers,
 * and a minimal reader for the exported .xlsx (a zip of XML parts).
 */
import { inflateRawSync } from "node:zlib";

import { expect, type Browser, type Locator, type Page } from "@playwright/test";

import { login, setPrefs, tr } from "../../helpers";
import type { SeedUser } from "../../fixtures/users";

export const LANG = "en" as const;

export function t(key: string, vars: Record<string, string> = {}): string {
  return tr(LANG, key, vars);
}

/** A fresh browser context logged in as `who`, light theme, English. */
export async function pageAs(browser: Browser, who: SeedUser, width = 1280): Promise<Page> {
  const context = await browser.newContext({ viewport: { width, height: 900 }, acceptDownloads: true });
  const page = await context.newPage();
  await login(page, who);
  await setPrefs(page, { theme: "light", lang: LANG });
  return page;
}

/** "38000.00" as the screens print it in English ("38,000.00"). */
export function sdg(amount: string): RegExp {
  const negative = amount.startsWith("-");
  const [int = "0", frac = "00"] = amount.replace(/^-/, "").split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return new RegExp(`${negative ? "-" : ""}${grouped}\\.${frac}`);
}

/** The amount a money element shows, as the API writes it ("SDG 13,500.00" -> "13500.00"). */
export async function amountOf(locator: Locator): Promise<string> {
  const text = (await locator.textContent()) ?? "";
  return text.replace(/[^\d.-]/g, "");
}

/** The data rows of a report section: table rows on wide screens, cards on narrow ones. */
export function sectionRows(page: Page, section: string): Locator {
  return page
    .getByTestId(`section-${section}`)
    .locator(
      '[data-slot="data-table"][data-mode="table"] tbody tr, ' +
        '[data-slot="data-table-cards"] [role="listitem"]:not([data-slot="data-table-totals"])',
    );
}

/** The totals row (table footer) or totals card of a report section. */
export function sectionTotals(page: Page, section: string): Locator {
  return page.getByTestId(`section-${section}`).locator('[data-slot="data-table-totals"]');
}

/** A report viewer finished loading: its figures are on screen. */
export async function reportLoaded(page: Page): Promise<void> {
  await expect(page.getByTestId("report-metrics")).toBeVisible();
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
