/**
 * The browser side of the booking form's proof-of-work (ADR 0029 F), the same rule as
 * `backend/domain/proof_of_work.py`: find a nonce (decimal digits here) so that
 * `SHA-256(challenge + nonce)` starts with `bits` zero bits. The search counts up from 0, so it
 * returns the same nonce as the backend's `solve()` for the same challenge (vitest checks this
 * on fixed vectors). Pure: the worker (`pow.worker.ts`) and the main-thread fallback both call it
 * in slices so the page never freezes.
 */
import { sha256 } from "./sha256";

/** Nonces tried between two progress reports (a few milliseconds of work). */
export const SLICE = 4096;

/** How many leading bits of `digest` are zero. */
export function leadingZeroBits(digest: Uint8Array): number {
  let count = 0;
  for (const byte of digest) {
    if (byte === 0) {
      count += 8;
      continue;
    }
    return count + Math.clz32(byte) - 24;
  }
  return count;
}

function asciiBytes(text: string): Uint8Array {
  const out = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i++) out[i] = text.charCodeAt(i) & 0xff;
  return out;
}

const ASCII_ONLY = /^[\x20-\x7e]*$/u;

/** Whether `SHA-256(token + nonce)` starts with `bits` zero bits. */
export function solves(token: string, nonce: string, bits: number): boolean {
  const text = token + nonce;
  const bytes = ASCII_ONLY.test(text) ? asciiBytes(text) : new TextEncoder().encode(text);
  return leadingZeroBits(sha256(bytes)) >= bits;
}

/**
 * Tries the nonces `start .. start + count - 1` and returns the first that solves `token`, or
 * null. The challenge is ASCII (`<id>.<expires>.<bits>.<mac>`), so its bytes are made once.
 */
export function solveRange(token: string, bits: number, start: number, count: number): string | null {
  const prefix = ASCII_ONLY.test(token) ? asciiBytes(token) : new TextEncoder().encode(token);
  const buffer = new Uint8Array(prefix.length + 20);
  buffer.set(prefix);
  for (let n = start; n < start + count; n++) {
    const digits = String(n);
    for (let i = 0; i < digits.length; i++) buffer[prefix.length + i] = digits.charCodeAt(i);
    const digest = sha256(buffer.subarray(0, prefix.length + digits.length));
    if (leadingZeroBits(digest) >= bits) return digits;
  }
  return null;
}

/** The first decimal nonce from 0 that solves `token` (tests; the UI searches in slices). */
export function solve(token: string, bits: number): string {
  for (let start = 0; ; start += SLICE) {
    const found = solveRange(token, bits, start, SLICE);
    if (found !== null) return found;
  }
}

/** About how many tries `bits` needs on average (for the progress text). */
export function expectedTries(bits: number): number {
  return 2 ** Math.max(0, bits);
}
