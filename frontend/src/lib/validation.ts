import type { TFunction } from "i18next";
import { z } from "zod";

/**
 * Translatable validation messages.
 *
 * Zod schemas are built once at module load, before the user picks a
 * language, so messages are stored as i18n references and translated when
 * rendered (FormMessage). That way switching language re-translates errors
 * that are already on screen.
 *
 *   z.string().min(1, vmsg("validation.required"))
 *   z.string().min(8, vmsg("validation.minLength", { count: 8 }))
 *
 * Keys without a namespace prefix are in `common`; others use "ns:key".
 */
const PREFIX = "$t:";

export function vmsg(key: string, params?: Record<string, string | number>): string {
  return params ? `${PREFIX}${key}|${JSON.stringify(params)}` : `${PREFIX}${key}`;
}

export interface DecodedMessage {
  key: string;
  params: Record<string, string | number>;
}

export function decodeMessage(message: string): DecodedMessage | null {
  if (!message.startsWith(PREFIX)) return null;
  const body = message.slice(PREFIX.length);
  const sep = body.indexOf("|");
  if (sep === -1) return { key: body, params: {} };
  try {
    return { key: body.slice(0, sep), params: JSON.parse(body.slice(sep + 1)) as Record<string, string | number> };
  } catch {
    return { key: body.slice(0, sep), params: {} };
  }
}

/**
 * Translates a key that is only known at runtime. Typed `t` only accepts
 * literal keys, so the single unchecked cast lives here.
 */
export function translateKey(t: TFunction, key: string, params: Record<string, unknown> = {}): string {
  return (t as unknown as (k: string, o: Record<string, unknown>) => string)(key, params);
}

/** Renders a form error message: i18n reference or plain server text. */
export function translateMessage(t: TFunction, message: string | undefined): string | undefined {
  if (!message) return undefined;
  const decoded = decodeMessage(message);
  return decoded ? translateKey(t, decoded.key, decoded.params) : message;
}

let configured = false;

/** Default messages for issues a schema did not customize. */
export function configureZodMessages(): void {
  if (configured) return;
  configured = true;
  z.config({
    customError: (issue) => {
      switch (issue.code) {
        case "invalid_type":
          return issue.input === undefined || issue.input === null || issue.input === ""
            ? vmsg("validation.required")
            : vmsg("validation.invalid");
        case "too_small":
          if (issue.origin === "string") {
            return Number(issue.minimum) <= 1
              ? vmsg("validation.required")
              : vmsg("validation.minLength", { count: Number(issue.minimum) });
          }
          return vmsg("validation.invalid");
        case "too_big":
          if (issue.origin === "string") return vmsg("validation.maxLength", { count: Number(issue.maximum) });
          return vmsg("validation.invalid");
        case "invalid_value":
          return vmsg("validation.selectOption");
        default:
          return vmsg("validation.invalid");
      }
    },
  });
}

configureZodMessages();

/** Sudanese mobile numbers as typed at reception: 10 digits starting with 0. */
export const phoneSchema = z
  .string()
  .trim()
  .regex(/^0\d{9}$/, vmsg("validation.phone"));

export const requiredString = z.string().trim().min(1, vmsg("validation.required"));
