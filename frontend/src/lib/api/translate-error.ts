import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import i18n from "@/i18n";

import { CLIENT_ERROR_CODES, toApiError, type ApiError } from "./errors";

/**
 * Translated, user-facing text for an error code (errors namespace).
 * Unknown codes fall back to the server message, then to a generic text.
 */
export function translateError(codeOrError: string | ApiError, t = i18n.t.bind(i18n)): string {
  const error = typeof codeOrError === "string" ? null : codeOrError;
  const code = typeof codeOrError === "string" ? codeOrError : codeOrError.code;
  const lookup = t as unknown as (key: string, opts: Record<string, unknown>) => string;
  const missing = "\u0000missing";
  const translated = lookup(`errors:${code}`, { defaultValue: missing });
  if (translated !== missing) return translated;
  if (error?.message) return error.message;
  return lookup(`errors:${CLIENT_ERROR_CODES.unknown}`, {});
}

export function useTranslateError(): (error: unknown) => string {
  const { t } = useTranslation();
  return useCallback(
    (error: unknown) => {
      const apiError = typeof error === "string" ? error : toApiError(error);
      return translateError(apiError, t);
    },
    [t],
  );
}
