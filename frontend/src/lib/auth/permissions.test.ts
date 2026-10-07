import { describe, expect, it } from "vitest";

import { hasPermission, isKnownRole } from "./permissions";

describe("hasPermission", () => {
  const cashier = { roles: ["cashier"], permissions: ["billing.approve_invoice", "payments.take_payment"] };

  it("requires a user", () => {
    expect(hasPermission(null, "x.y")).toBe(false);
    expect(hasPermission(undefined, undefined)).toBe(false);
  });

  it("allows entries without a permission to any logged-in user", () => {
    expect(hasPermission(cashier, undefined)).toBe(true);
    expect(hasPermission(cashier, [])).toBe(true);
  });

  it("checks all/any", () => {
    expect(hasPermission(cashier, "billing.approve_invoice")).toBe(true);
    expect(hasPermission(cashier, "lab.approve_result")).toBe(false);
    expect(hasPermission(cashier, ["billing.approve_invoice", "lab.approve_result"])).toBe(false);
    expect(hasPermission(cashier, ["billing.approve_invoice", "lab.approve_result"], "any")).toBe(true);
  });

  it("lets the admin role see everything", () => {
    expect(hasPermission({ roles: ["admin"], permissions: [] }, "anything.at_all")).toBe(true);
  });

  it("does not give doctors billing by default", () => {
    expect(hasPermission({ roles: ["doctor"], permissions: ["clinical.view"] }, "billing.approve_invoice")).toBe(false);
  });

  it("knows the eleven roles", () => {
    expect(isKnownRole("cashier_supervisor")).toBe(true);
    expect(isKnownRole("superhero")).toBe(false);
  });
});
