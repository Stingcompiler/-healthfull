import { describe, expect, it } from "vitest";

import { hasPermission, isKnownRole, mixesDeviceRole, toggleRole } from "./permissions";

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

describe("the display role is held alone (ADR 0019)", () => {
  it("ticking the display role clears every person's role", () => {
    expect(toggleRole(["nurse", "doctor"], "display", true)).toEqual(["display"]);
  });

  it("ticking a person's role clears the display role", () => {
    expect(toggleRole(["display"], "receptionist", true)).toEqual(["receptionist"]);
  });

  it("person roles combine and untick normally, in the roles' order", () => {
    expect(toggleRole(["nurse"], "doctor", true)).toEqual(["doctor", "nurse"]);
    expect(toggleRole(["doctor", "nurse"], "doctor", false)).toEqual(["nurse"]);
    expect(toggleRole(["display"], "display", false)).toEqual([]);
  });

  it("detects a mixed set", () => {
    expect(mixesDeviceRole(["display", "nurse"])).toBe(true);
    expect(mixesDeviceRole(["display"])).toBe(false);
    expect(mixesDeviceRole(["nurse", "doctor"])).toBe(false);
  });
});
