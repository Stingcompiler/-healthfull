/**
 * Insurance claims screens for the responsive matrix, besides /claims (listed in e2e/routes.ts).
 * Owned by the claims module. Every screen is checked with data in it: the backend fixture
 * `claims_screens` builds, once for the run, a payer with accrued shares, a draft claim, an
 * answered claim (accepted, partial, rebilled and unresolved rejections) and two payer
 * payments (a transfer and a cheque still to clear). Each `ready` waits for loaded content,
 * never for the page heading alone (it renders before the data).
 */
import type { Locator, Page } from "@playwright/test";

import { fixture } from "../helpers";
import { appRoute, type AppRoute } from "../route-kit";

interface Screens {
  payer: { id: number; code: string };
  draft_claim: { id: number; number: string };
  answered_claim: { id: number; number: string };
}

let screens: Promise<Screens> | undefined;

/** The claim screens' data, built once per worker (the fixture itself is idempotent). */
export function claimScreens(): Promise<Screens> {
  screens ??= fixture<Screens>("claims_screens", {});
  return screens;
}

/** The first loaded row of a list: a card on phones, a table row from md up. */
function firstRow(page: Page, cardTestId: string): Locator {
  return page
    .locator(
      `[data-testid="${cardTestId}"], ` +
        '[data-slot="data-table"][data-mode="table"] tbody tr:not(:has([data-slot="skeleton"])):not(:has(td[colspan]))',
    )
    .first();
}

export const routes: readonly AppRoute[] = [
  appRoute("claims-receivables", "/claims", {
    resolve: async () => {
      await claimScreens();
      return "/claims";
    },
    ready: (page) => firstRow(page, "receivable-row"),
  }),
  appRoute("claims-batches", "/claims/batches", {
    resolve: async () => {
      await claimScreens();
      return "/claims/batches";
    },
    ready: (page) => firstRow(page, "claim-row"),
  }),
  appRoute("claims-build", "/claims/new", {
    resolve: async () => `/claims/new?payer=${String((await claimScreens()).payer.id)}`,
    ready: (page) => page.getByTestId("accrued-line").first(),
  }),
  appRoute("claims-detail", "/claims/$claimId", {
    resolve: async () => `/claims/${String((await claimScreens()).answered_claim.id)}`,
    ready: (page) => firstRow(page, "claim-line"),
  }),
  appRoute("claims-detail-draft", "/claims/$claimId", {
    resolve: async () => `/claims/${String((await claimScreens()).draft_claim.id)}`,
    ready: (page) => page.getByTestId("claim-submit"),
  }),
  appRoute("claims-print", "/claims/$claimId/print", {
    resolve: async () => `/claims/${String((await claimScreens()).answered_claim.id)}/print`,
    ready: (page) => page.getByTestId("claim-print"),
  }),
  appRoute("claims-payments", "/claims/payments", {
    resolve: async () => {
      await claimScreens();
      return "/claims/payments";
    },
    ready: (page) => firstRow(page, "payer-payment-row"),
  }),
  appRoute("claims-aging", "/claims/aging", {
    resolve: async () => {
      await claimScreens();
      return "/claims/aging";
    },
    ready: (page) => firstRow(page, "aging-row"),
  }),
];
