import { beforeEach, describe, expect, it } from "vitest";

import {
  ATTEMPT_STORAGE_KEY,
  attemptFor,
  clearAttempt,
  endsAttempt,
  loadAttempt,
  withProof,
  type AttemptDetails,
} from "./attempt";

function memoryStore() {
  const map = new Map<string, string>();
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => {
      map.set(k, v);
    },
    removeItem: (k: string) => {
      map.delete(k);
    },
    map,
  };
}

const details: AttemptDetails = {
  doctor_id: 3,
  starts_at: "2026-11-02T08:00:00+03:00",
  contact_name: "Amna Ali",
  contact_phone: "0912345678",
};

describe("guest booking attempt (Idempotency-Key)", () => {
  let store: ReturnType<typeof memoryStore>;
  let counter: number;
  const makeKey = () => `00000000-0000-4000-8000-00000000000${String(++counter)}`;

  beforeEach(() => {
    store = memoryStore();
    counter = 0;
  });

  it("makes one key per attempt and keeps it across retries", () => {
    const first = attemptFor(details, store, makeKey);
    const retry = attemptFor({ ...details }, store, makeKey);
    expect(retry.key).toBe(first.key);
    expect(counter).toBe(1);
    expect(store.map.has(ATTEMPT_STORAGE_KEY)).toBe(true);
  });

  it("survives a reload (sessionStorage) with its solved proof, so a retry resends the same body", () => {
    const first = attemptFor(details, store, makeKey);
    withProof(first, { challenge: "c.1.18.m", nonce: "42" }, store);
    const reloaded = loadAttempt(store);
    expect(reloaded?.key).toBe(first.key);
    expect(reloaded?.proof).toEqual({ challenge: "c.1.18.m", nonce: "42" });
    const again = attemptFor(details, store, makeKey);
    expect(again.proof?.nonce).toBe("42");
  });

  it("changed details start a new attempt with a new key and no proof", () => {
    const first = attemptFor(details, store, makeKey);
    withProof(first, { challenge: "c", nonce: "1" }, store);
    const other = attemptFor({ ...details, starts_at: "2026-11-02T08:15:00+03:00" }, store, makeKey);
    expect(other.key).not.toBe(first.key);
    expect(other.proof).toBeNull();
  });

  it("a cleared attempt (answered) gives a new key next time", () => {
    const first = attemptFor(details, store, makeKey);
    clearAttempt(store);
    expect(loadAttempt(store)).toBeNull();
    expect(attemptFor(details, store, makeKey).key).not.toBe(first.key);
  });

  it("ignores a damaged stored value", () => {
    store.setItem(ATTEMPT_STORAGE_KEY, "{not json");
    expect(loadAttempt(store)).toBeNull();
    store.setItem(ATTEMPT_STORAGE_KEY, JSON.stringify({ key: 1 }));
    expect(loadAttempt(store)).toBeNull();
  });

  it("a server answer ends the attempt; a lost answer keeps it for a retry", () => {
    expect(endsAttempt(409)).toBe(true);
    expect(endsAttempt(400)).toBe(true);
    expect(endsAttempt(429)).toBe(true);
    expect(endsAttempt(0)).toBe(false); // network
    expect(endsAttempt(502)).toBe(false);
    expect(endsAttempt(500)).toBe(false);
  });

  it("makes RFC 4122 version 4 keys by default", () => {
    const attempt = attemptFor(details, store);
    expect(attempt.key).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u);
  });
});
