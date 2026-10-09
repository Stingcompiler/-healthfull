/**
 * Administration screens for the responsive matrix, besides /administration and its
 * sections (listed in e2e/routes.ts). Owned by the admin module.
 * Detail screens open the seeded CASH price list and the AMAN payer (seed_e2e).
 */
import { seededCatalog } from "../helpers";
import { appRoute, type AppRoute } from "../route-kit";

export const routes: readonly AppRoute[] = [
  appRoute("admin-policies", "/administration/policies"),
  appRoute("admin-departments", "/administration/departments"),
  appRoute("admin-reason-codes", "/administration/reason-codes"),
  appRoute("admin-price-list", "/administration/price-lists/$priceListId", {
    resolve: async () => {
      const id = (await seededCatalog()).price_lists.CASH;
      if (id === undefined) throw new Error("seed_e2e has no CASH price list");
      return `/administration/price-lists/${String(id)}`;
    },
  }),
  appRoute("admin-payer", "/administration/payers/$payerId", {
    resolve: async () => {
      const payer = (await seededCatalog()).payers.AMAN;
      if (payer === undefined) throw new Error("seed_e2e has no AMAN payer");
      return `/administration/payers/${String(payer.id)}`;
    },
  }),
];
