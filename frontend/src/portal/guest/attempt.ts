/**
 * One guest booking attempt and its `Idempotency-Key` (ADR 0029 C): a UUID made once per
 * attempt and kept in sessionStorage, so a retry after a lost answer (timeout, dropped
 * connection, reload) sends the very same request and gets the very same booking back
 * (`replayed`), never a second one.
 *
 * The server hashes the whole body (details, challenge and nonce) with the key, so the solved
 * proof is kept with it and a retry resends both unchanged. Changed details start a new attempt
 * (a new key and a new proof). An answer from the server, success or refusal, ends the attempt:
 * a refusal is checked afresh next time and its challenge is already spent.
 */

export interface AttemptDetails {
  doctor_id: number;
  starts_at: string;
  contact_name: string;
  contact_phone: string;
}

export interface AttemptProof {
  challenge: string;
  nonce: string;
}

export interface Attempt {
  key: string;
  details: AttemptDetails;
  proof: AttemptProof | null;
}

export const ATTEMPT_STORAGE_KEY = "portal.guestBooking.attempt";

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function defaultStore(): Store | null {
  try {
    return window.sessionStorage;
  } catch {
    return null; // storage blocked: the attempt then lives only in memory
  }
}

let memory: Attempt | null = null;

function newKey(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  // crypto.randomUUID needs a secure context too; getRandomValues does not (plain HTTP LAN).
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function isAttempt(value: unknown): value is Attempt {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  const d = v.details as Record<string, unknown> | undefined;
  return (
    typeof v.key === "string" &&
    typeof d === "object" &&
    typeof d.doctor_id === "number" &&
    typeof d.starts_at === "string" &&
    typeof d.contact_name === "string" &&
    typeof d.contact_phone === "string"
  );
}

/** The unfinished attempt of this tab, if any. */
export function loadAttempt(store: Store | null = defaultStore()): Attempt | null {
  if (!store) return memory;
  try {
    const raw = store.getItem(ATTEMPT_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isAttempt(parsed) ? { ...parsed, proof: parsed.proof ?? null } : null;
  } catch {
    return null;
  }
}

export function saveAttempt(attempt: Attempt, store: Store | null = defaultStore()): void {
  memory = attempt;
  try {
    store?.setItem(ATTEMPT_STORAGE_KEY, JSON.stringify(attempt));
  } catch {
    // quota or privacy mode: memory keeps it for this page
  }
}

export function clearAttempt(store: Store | null = defaultStore()): void {
  memory = null;
  try {
    store?.removeItem(ATTEMPT_STORAGE_KEY);
  } catch {
    // nothing to clear
  }
}

function sameDetails(a: AttemptDetails, b: AttemptDetails): boolean {
  return (
    a.doctor_id === b.doctor_id &&
    a.starts_at === b.starts_at &&
    a.contact_name === b.contact_name &&
    a.contact_phone === b.contact_phone
  );
}

/**
 * The attempt for these details: the stored one when the details are the same (a retry keeps
 * its key and proof), else a new one with a new key (saved).
 */
export function attemptFor(
  details: AttemptDetails,
  store: Store | null = defaultStore(),
  makeKey: () => string = newKey,
): Attempt {
  const current = loadAttempt(store);
  if (current && sameDetails(current.details, details)) return current;
  const fresh: Attempt = { key: makeKey(), details: { ...details }, proof: null };
  saveAttempt(fresh, store);
  return fresh;
}

/** Keeps the solved proof with the attempt, so a retry does not solve (or spend) another. */
export function withProof(attempt: Attempt, proof: AttemptProof, store: Store | null = defaultStore()): Attempt {
  const next = { ...attempt, proof };
  saveAttempt(next, store);
  return next;
}

/**
 * Whether an error ends the attempt: any answer the server gave (4xx) does; a lost answer
 * (network, timeout, 5xx, a proxy page) keeps it for a retry with the same key.
 */
export function endsAttempt(status: number): boolean {
  return status >= 400 && status < 500;
}
