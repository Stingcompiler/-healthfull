import type { Language } from "@/lib/preferences";

/**
 * Locale-aware formatting. Money arrives from the API as decimal strings
 * ("10000.00") and is formatted without ever converting to a float
 * (Intl.NumberFormat accepts decimal strings exactly).
 *
 * Digits: Sudanese clinics commonly use Latin digits even in Arabic UI, so
 * that is the default; a center setting can switch Arabic UI to
 * Arabic-Indic digits (ARCHITECTURE 5.2).
 */
export type DigitStyle = "latn" | "arab";

export const CURRENCY = "SDG";
/** Center time zone; every date shown in the UI uses it. */
export const CENTER_TIME_ZONE = "Africa/Khartoum";

let arabicDigits: DigitStyle = "latn";

/** Called once the center profile is loaded (later phase). */
export function setArabicDigitStyle(style: DigitStyle): void {
  arabicDigits = style;
}

export function localeFor(language: Language, digits: DigitStyle = arabicDigits): string {
  return language === "ar" ? `ar-SD-u-nu-${digits}` : "en-SD";
}

const DECIMAL_RE = /^-?\d+(\.\d+)?$/;

export type MoneyInput = string | number | bigint;

/** Validates and normalizes a money value to a decimal string. */
export function toDecimalString(value: MoneyInput): string {
  if (typeof value === "bigint") return value.toString();
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new RangeError(`Invalid money amount: ${String(value)}`);
    // Numbers only come from literals in UI code (e.g. 0); render exactly 2 places.
    return value.toFixed(2);
  }
  const trimmed = value.trim();
  if (!DECIMAL_RE.test(trimmed)) throw new RangeError(`Invalid money amount: "${value}"`);
  return trimmed;
}

export function isNegativeAmount(value: MoneyInput): boolean {
  return toDecimalString(value).startsWith("-");
}

export function isZeroAmount(value: MoneyInput): boolean {
  return /^-?0+(\.0+)?$/.test(toDecimalString(value));
}

export interface MoneyFormatOptions {
  /** Show the currency (ج.س / SDG). Default true. */
  currency?: boolean;
  /** Always show + for positive amounts (e.g. deltas). */
  signed?: boolean;
  digits?: DigitStyle;
}

const moneyFormatters = new Map<string, Intl.NumberFormat>();

function moneyFormatter(locale: string, currency: boolean, signed: boolean): Intl.NumberFormat {
  const key = `${locale}|${String(currency)}|${String(signed)}`;
  let nf = moneyFormatters.get(key);
  if (!nf) {
    nf = new Intl.NumberFormat(locale, {
      ...(currency ? { style: "currency", currency: CURRENCY, currencyDisplay: "symbol" } : {}),
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
      signDisplay: signed ? "exceptZero" : "auto",
    });
    moneyFormatters.set(key, nf);
  }
  return nf;
}

export function formatMoney(value: MoneyInput, language: Language, options: MoneyFormatOptions = {}): string {
  const { currency = true, signed = false, digits } = options;
  const locale = localeFor(language, digits);
  const decimal = toDecimalString(value) as Intl.StringNumericLiteral;
  return moneyFormatter(locale, currency, signed).format(decimal);
}

export function formatNumber(value: number, language: Language, options: Intl.NumberFormatOptions = {}): string {
  return new Intl.NumberFormat(localeFor(language), options).format(value);
}

export type DateFormat = "date" | "datetime" | "time" | "long";

const DATE_OPTIONS: Record<DateFormat, Intl.DateTimeFormatOptions> = {
  date: { day: "numeric", month: "short", year: "numeric" },
  long: { weekday: "long", day: "numeric", month: "long", year: "numeric" },
  datetime: { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" },
  time: { hour: "numeric", minute: "2-digit" },
};

export function toDate(value: string | number | Date): Date {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) throw new RangeError(`Invalid date: ${String(value)}`);
  return date;
}

export function formatDate(
  value: string | number | Date,
  language: Language,
  format: DateFormat = "date",
  timeZone: string = CENTER_TIME_ZONE,
): string {
  return new Intl.DateTimeFormat(localeFor(language), { ...DATE_OPTIONS[format], timeZone }).format(toDate(value));
}

const RELATIVE_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["week", 7 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
  ["second", 1],
];

export function formatRelative(value: string | number | Date, language: Language, now: Date = new Date()): string {
  const seconds = Math.round((toDate(value).getTime() - now.getTime()) / 1000);
  const rtf = new Intl.RelativeTimeFormat(localeFor(language), { numeric: "auto" });
  for (const [unit, size] of RELATIVE_UNITS) {
    if (Math.abs(seconds) >= size || unit === "second") {
      return rtf.format(Math.round(seconds / size), unit);
    }
  }
  return rtf.format(0, "second");
}

/**
 * Compares two decimal strings exactly (for sorting money columns) without
 * converting to floating point. Returns -1, 0 or 1.
 */
export function compareDecimal(a: MoneyInput, b: MoneyInput): -1 | 0 | 1 {
  const parse = (v: MoneyInput) => {
    const s = toDecimalString(v);
    const negative = s.startsWith("-");
    const [int = "0", frac = ""] = (negative ? s.slice(1) : s).split(".");
    return { negative, int: int.replace(/^0+(?=\d)/, ""), frac };
  };
  const x = parse(a);
  const y = parse(b);
  const zero = (p: { int: string; frac: string }) => /^0*$/.test(p.int) && /^0*$/.test(p.frac);
  const xNeg = x.negative && !zero(x);
  const yNeg = y.negative && !zero(y);
  if (xNeg !== yNeg) return xNeg ? -1 : 1;
  const width = Math.max(x.frac.length, y.frac.length);
  const xs = x.int.padStart(32, "0") + x.frac.padEnd(width, "0");
  const ys = y.int.padStart(32, "0") + y.frac.padEnd(width, "0");
  const cmp = xs < ys ? -1 : xs > ys ? 1 : 0;
  return (xNeg ? -cmp : cmp) as -1 | 0 | 1;
}
