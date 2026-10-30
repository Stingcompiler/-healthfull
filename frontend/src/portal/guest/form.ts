/**
 * The guest booking and guest sign-in forms (ADR 0029 D). The checks here only spare a round
 * trip; the server decides (`domain.guest_booking.phone_key`, `validate_contact_name`,
 * `normalize_reference`) and its error codes are shown when it refuses.
 */
import { z } from "zod";

import { vmsg } from "@/lib/validation";

/** Folds Arabic-Indic digits to ASCII (people type either on Sudanese phones). */
export function foldDigits(text: string): string {
  return text
    .replace(/[\u0660-\u0669]/gu, (d) => String(d.charCodeAt(0) - 0x0660))
    .replace(/[\u06f0-\u06f9]/gu, (d) => String(d.charCodeAt(0) - 0x06f0));
}

/**
 * International digits of a typed phone, or null: the same folding as the server's
 * `phone_key` (local Sudanese `0912 345 678` or `912345678` become `249912345678`; `+` or `00`
 * keep another country code).
 */
export function phoneKey(raw: string): string | null {
  const compact = foldDigits(raw)
    .trim()
    .replace(/[\s\-().]/gu, "");
  let digits: string;
  if (compact.startsWith("+")) digits = compact.slice(1);
  else if (compact.startsWith("00")) digits = compact.slice(2);
  else if (compact.startsWith("0")) digits = `249${compact.slice(1)}`;
  else if (compact.length === 9) digits = `249${compact}`;
  else digits = compact;
  return /^\d{8,15}$/u.test(digits) ? digits : null;
}

export const NAME_MAX = 200;

export const guestContactSchema = z.object({
  contact_name: z
    .string()
    .trim()
    .min(1, vmsg("portal:guest.form.nameRequired"))
    .max(NAME_MAX, vmsg("validation.maxLength", { count: NAME_MAX })),
  contact_phone: z
    .string()
    .trim()
    .max(30, vmsg("portal:guest.form.phoneInvalid"))
    .refine((v) => phoneKey(v) !== null, vmsg("portal:guest.form.phoneInvalid")),
});
export type GuestContactValues = z.infer<typeof guestContactSchema>;

const REFERENCE_ALPHABET = /^[A-Z2-7]{10}$/u;

/** A typed reference as the server compares it: upper case, without spaces or dashes. */
export function normalizeReference(raw: string): string {
  return foldDigits(raw)
    .toUpperCase()
    .replace(/[\s\-_.]/gu, "");
}

export const guestSignInSchema = z.object({
  reference: z
    .string()
    .trim()
    .refine((v) => REFERENCE_ALPHABET.test(normalizeReference(v)), vmsg("portal:guest.signIn.referenceInvalid")),
  pin: z
    .string()
    .trim()
    .refine((v) => /^\d{6}$/u.test(foldDigits(v).replace(/[\s\-_.]/gu, "")), vmsg("portal:guest.signIn.pinInvalid")),
});
export type GuestSignInValues = z.infer<typeof guestSignInSchema>;
