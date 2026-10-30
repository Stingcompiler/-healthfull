import { describe, expect, it } from "vitest";

import { GUEST_STEPS, revealed, slotComplete, stepNumber, stepState } from "./steps";

describe("guest stepper", () => {
  it("numbers the four steps in order", () => {
    expect(GUEST_STEPS.map(stepNumber)).toEqual([1, 2, 3, 4]);
  });

  it("marks earlier steps done, the open one current and later ones upcoming", () => {
    expect(GUEST_STEPS.map((s) => stepState(s, "slot"))).toEqual(["current", "upcoming", "upcoming", "upcoming"]);
    expect(GUEST_STEPS.map((s) => stepState(s, "contact"))).toEqual(["done", "current", "upcoming", "upcoming"]);
    expect(GUEST_STEPS.map((s) => stepState(s, "review"))).toEqual(["done", "done", "current", "upcoming"]);
  });

  it("reads every step done on the confirmation", () => {
    expect(GUEST_STEPS.map((s) => stepState(s, "done"))).toEqual(["done", "done", "done", "done"]);
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
