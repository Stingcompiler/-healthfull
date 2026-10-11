import { describe, expect, it } from "vitest";

import { hasPickable, isPickable, overridePicks, pickedTotal } from "./batches";

const usable = { batch_id: 1, expired: false };
const expired = { batch_id: 2, expired: true };
const later = { batch_id: 3, expired: false };

describe("batch override choices (server rule: an expired batch is never dispensed)", () => {
  it("never offers an expired batch, even in override mode", () => {
    expect(isPickable(usable)).toBe(true);
    expect(isPickable(expired)).toBe(false);
    expect(hasPickable([expired])).toBe(false);
    expect(hasPickable([expired, later])).toBe(true);
    expect(hasPickable([])).toBe(false);
  });

  it("drops a pick typed for an expired batch instead of sending it", () => {
    const picks = { "1": "2", "2": "5", "3": "1" };
    expect(overridePicks([usable, expired, later], picks)).toEqual([
      { batch_id: 1, quantity: 2 },
      { batch_id: 3, quantity: 1 },
    ]);
    expect(pickedTotal([usable, expired, later], picks)).toBe(3);
  });

  it("counts empty entries as none and refuses non-whole quantities of usable batches", () => {
    expect(pickedTotal([usable, later], { "1": "", "3": "4" })).toBe(4);
    expect(pickedTotal([usable, later], { "1": "1.5" })).toBeNaN();
    // A bad entry on an expired batch is ignored: it is never sent.
    expect(pickedTotal([usable, expired], { "1": "2", "2": "x" })).toBe(2);
    expect(overridePicks([usable], { "1": "0" })).toEqual([]);
  });
});
