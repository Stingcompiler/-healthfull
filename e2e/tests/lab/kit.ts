/**
 * Shared steps of the lab specs: a logged-in page per seed user (English UI, so the specs read
 * the en texts through `t`), and the backend lab fixtures.
 */
import { expect, type Browser, type Page } from "@playwright/test";

import type { SeedUser } from "../../fixtures/users";
import { fixture, login, setPrefs, tr } from "../../helpers";

export const LANG = "en" as const;

export function t(key: string, vars: Record<string, string> = {}): string {
  return tr(LANG, key, vars);
}

export interface LabOrder {
  patient: { id: number; file_no: string; full_name_en: string };
  visit: { id: number; number: string };
  lab_lines: {
    id: number;
    service: string;
    billing_status: string;
    fulfilment_status: string;
  }[];
}

export interface LabProgress {
  line: number;
  sample: { id: number; accession_no: string };
  stage: string;
  versions: { id: number; version_no: number; status: string }[];
}

/** A new adult patient whose lab tests are ordered, invoiced and (unless pay=false) paid. */
export function labOrder(params: { tests?: string[]; pay?: boolean; patient_fields?: object } = {}): Promise<LabOrder> {
  return fixture<LabOrder>("lab_order", params);
}

export function labProgress(params: Record<string, unknown>): Promise<LabProgress> {
  return fixture<LabProgress>("lab_progress", params);
}

export function firstLine(order: LabOrder): number {
  const line = order.lab_lines[0];
  if (!line) throw new Error("lab_order returned no lab line");
  return line.id;
}

/** A fresh browser context logged in as `who`, light theme, English. window.print is a no-op. */
export async function pageAs(browser: Browser, who: SeedUser, width = 1280): Promise<Page> {
  const context = await browser.newContext({
    viewport: { width, height: 900 },
  });
  await context.addInitScript(() => {
    window.print = () => undefined;
  });
  const page = await context.newPage();
  await login(page, who);
  await setPrefs(page, { theme: "light", lang: LANG });
  return page;
}

/** Opens one test on the bench and waits for it to load. */
export async function openTest(page: Page, lineId: number): Promise<void> {
  await page.goto(`/lab/results/${String(lineId)}`);
  await expect(page.getByTestId("sample-panel")).toBeVisible();
}

/** Picks an option of a shared Select by its accessible label. */
export async function choose(page: Page, label: string, option: string): Promise<void> {
  await page.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}
