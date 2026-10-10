/**
 * Display-only totals of the walk-in sale basket (price x quantity). The server prices and
 * totals the invoice; this never sends an amount. Whole cents with BigInt: never a float.
 */

const AMOUNT = /^(\d+)(?:\.(\d{1,2}))?$/;

function toCents(value: string): bigint | null {
  const match = AMOUNT.exec(value.trim());
  if (!match) return null;
  return BigInt(match[1] ?? "0") * 100n + BigInt((match[2] ?? "").padEnd(2, "0"));
}

function fromCents(cents: bigint): string {
  return `${String(cents / 100n)}.${String(cents % 100n).padStart(2, "0")}`;
}

/** `price` (a "300.00" string) times a whole quantity, as a "900.00" string. */
export function lineTotal(price: string, quantity: number): string | null {
  const cents = toCents(price);
  if (cents === null || !Number.isSafeInteger(quantity) || quantity < 0) return null;
  return fromCents(cents * BigInt(quantity));
}

/** The sum of "0.00" strings; null when any is not an amount. */
export function sumAmounts(values: readonly (string | null)[]): string | null {
  let total = 0n;
  for (const v of values) {
    const cents = v === null ? null : toCents(v);
    if (cents === null) return null;
    total += cents;
  }
  return fromCents(total);
}
