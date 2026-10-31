import { describe, expect, it } from "vitest";

import { GUEST_STEPS, PATIENT_STEPS, revealed, slotComplete, stepNumber, stepState } from "./steps";

describe("guest stepper", () => {
  it("numbers the four steps in order", () => {
    expect(GUEST_STEPS.map((s) => stepNumber(GUEST_STEPS, s))).toEqual([1, 2, 3, 4]);
  });

  it("marks earlier steps done, the open one current and later ones upcoming", () => {
    expect(GUEST_STEPS.map((s) => stepState(GUEST_STEPS, s, "slot"))).toEqual([
      "current",
      "upcoming",
      "upcoming",
      "upcoming",
    ]);
    expect(GUEST_STEPS.map((s) => stepState(GUEST_STEPS, s, "contact"))).toEqual([
      "done",
      "current",
      "upcoming",
      "upcoming",
    ]);
    expect(GUEST_STEPS.map((s) => stepState(GUEST_STEPS, s, "review"))).toEqual([
      "done",
      "done",
      "current",
      "upcoming",
    ]);
  });

  it("reads every step done on the confirmation", () => {
    expect(GUEST_STEPS.map((s) => stepState(GUEST_STEPS, s, "done"))).toEqual(["done", "done", "done", "done"]);
  });
});

describe("patient stepper", () => {
  it("has two steps, no contact step and no confirmation step", () => {
    expect(PATIENT_STEPS.map((s) => stepNumber(PATIENT_STEPS, s))).toEqual([1, 2]);
    expect<readonly string[]>(PATIENT_STEPS).not.toContain("contact");
  });

  it("marks the slot step done on the review", () => {
    expect(PATIENT_STEPS.map((s) => stepState(PATIENT_STEPS, s, "slot"))).toEqual(["current", "upcoming"]);
    expect(PATIENT_STEPS.map((s) => stepState(PATIENT_STEPS, s, "review"))).toEqual(["done", "current"]);
  });
});

describe("slot step", () => {
  const none = { doctorId: null, day: null, start: null };

  it("reveals the day after a doctor and the time after a day", () => {
    expect(revealed(none)).toEqual({ day: false, time: false });
    expect(revealed({ ...none, doctorId: 3 })).toEqual({ day: true, time: false });
    expect(revealed({ doctorId: 3, day: "2026-11-02", start: null })).toEqual({ day: true, time: true });
    // A day without a doctor (never set by the chooser) shows nothing further.
    expect(revealed({ ...none, day: "2026-11-02" })).toEqual({ day: false, time: false });
  });

  it("is complete only with a doctor and a time", () => {
    expect(slotComplete(none)).toBe(false);
    expect(slotComplete({ doctorId: 3, day: "2026-11-02", start: null })).toBe(false);
    expect(slotComplete({ doctorId: 3, day: "2026-11-02", start: "2026-11-02T08:00:00Z" })).toBe(true);
  });
});
