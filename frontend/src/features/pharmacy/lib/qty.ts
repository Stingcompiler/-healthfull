/**
 * Whole-unit quantities typed at the pharmacy counter. Arabic-Indic digits are accepted (as at
 * the cashier's desk); the server judges every quantity, this only reads what was typed.
 */

const ARABIC_INDIC = /[٠-٩۰-۹]/g;

/** Latin digits for Arabic-Indic (and Persian) digits, spaces and separators dropped. */
export function normalizeDigits(raw: string): string {
  return raw
    .replace(ARABIC_INDIC, (d) => String((d.codePointAt(0) ?? 0) & 0xf))
    .replace(/[\s,٬]/g, "")
    .trim();
}

const WHOLE = /^\d+$/;
const SIGNED = /^[-−]?\d+$/;

/** A whole number >= `min`, or null when the text is not one. */
export function parseWhole(raw: string, min = 1): number | null {
  const value = normalizeDigits(raw);
  if (!WHOLE.test(value)) return null;
  const n = Number(value);
  return Number.isSafeInteger(n) && n >= min ? n : null;
}

/** A signed whole number other than zero, or null. */
export function parseSigned(raw: string): number | null {
  const value = normalizeDigits(raw).replace("−", "-");
  if (!SIGNED.test(value)) return null;
  const n = Number(value);
  return Number.isSafeInteger(n) && n !== 0 ? n : null;
}

const COST = /^\d+(\.\d{1,4})?$/;

/** A cost with up to four decimals as the API takes it, or null. */
export function parseCost(raw: string): string | null {
  const value = normalizeDigits(raw).replace("٫", ".");
  return COST.test(value) ? value : null;
}
