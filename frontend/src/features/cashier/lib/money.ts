/**
 * Exact display arithmetic on decimal strings, for the cashier's live hints only (change due,
 * the difference between counted and expected cash). The server computes and enforces every
 * amount; nothing here is sent as a rule. Works on whole cents with BigInt: never a float.
 */

const ARABIC_INDIC = /[٠-٩۰-۹]/g;

/** Latin digits for Arabic-Indic (and Persian) digits, separators and spaces dropped. */
export function normalizeAmountInput(raw: string): string {
  return raw
    .replace(ARABIC_INDIC, (d) => String((d.codePointAt(0) ?? 0) & 0xf))
    .replace(/[٫]/g, ".")
    .replace(/[\s,٬]/g, "")
    .trim();
}

const AMOUNT = /^-?\d+(\.\d{1,2})?$/;

/** True when `raw` is a money amount the API accepts (at most two decimals). */
export function isAmount(raw: string): boolean {
  return AMOUNT.test(normalizeAmountInput(raw));
}

/** Whole cents of a decimal string, or null when it is not an amount. */
export function toCents(raw: string): bigint | null {
  const value = normalizeAmountInput(raw);
  if (!AMOUNT.test(value)) return null;
  const negative = value.startsWith("-");
  const [int = "0", frac = ""] = (negative ? value.slice(1) : value).split(".");
  const cents = BigInt(int) * 100n + BigInt(frac.padEnd(2, "0"));
  return negative ? -cents : cents;
}

/** A decimal string with two places from whole cents. */
export function fromCents(cents: bigint): string {
  const negative = cents < 0n;
  const abs = negative ? -cents : cents;
  const int = abs / 100n;
  const frac = (abs % 100n).toString().padStart(2, "0");
  return `${negative ? "-" : ""}${int.toString()}.${frac}`;
}

/** `a - b` as a decimal string, or null when either is not an amount. */
export function subtractAmounts(a: string, b: string): string | null {
  const x = toCents(a);
  const y = toCents(b);
  if (x === null || y === null) return null;
  return fromCents(x - y);
}

/** Sum of decimal strings (display totals); null when any is not an amount. */
export function sumAmounts(values: readonly string[]): string | null {
  let total = 0n;
  for (const v of values) {
    const c = toCents(v);
    if (c === null) return null;
    total += c;
  }
  return fromCents(total);
}

/** -1, 0 or 1; null when either is not an amount. */
export function compareAmounts(a: string, b: string): -1 | 0 | 1 | null {
  const x = toCents(a);
  const y = toCents(b);
  if (x === null || y === null) return null;
  return x < y ? -1 : x > y ? 1 : 0;
}

/** The amount with its sign flipped, for showing money that leaves (never "-0.00"). */
export function negate(raw: string): string {
  const c = toCents(raw);
  return c === null ? raw : fromCents(-c);
}

export function isPositiveAmount(raw: string): boolean {
  const c = toCents(raw);
  return c !== null && c > 0n;
}
