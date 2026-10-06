/**
 * Contract guard: every error code the backend can put in an API response has
 * Arabic and English text in the `errors` namespace (ARCHITECTURE 4.11: "the
 * frontend maps `code` to translated text"). Without it the UI falls back to
 * the server's English `message`, also for Arabic users.
 *
 * The codes are read from the backend sources: DomainError(...) in domain/,
 * services and models (409 unless mapped otherwise), and the HTTP layer in
 * api/ (status map, ApiError, error responses). Adding a code there without
 * translating it fails `pnpm test` (and `make check`).
 */
import { describe, expect, it } from "vitest";

import { ar, en } from "@/i18n/resources";

const sources = import.meta.glob<string>(
  [
    "../../../../backend/api/**/*.py",
    "../../../../backend/apps/**/*.py",
    "../../../../backend/domain/**/*.py",
    "!../../../../backend/**/tests/**",
    "!../../../../backend/**/migrations/**",
    "!../../../../backend/**/management/**",
  ],
  { query: "?raw", import: "default", eager: true },
);

const CODE = String.raw`"([A-Z][A-Z0-9_]+)"`;
const PATTERNS: readonly RegExp[] = [
  // raise DomainError("STOCK_INSUFFICIENT", ...), also split over lines
  new RegExp(String.raw`\bDomainError\(\s*${CODE}`, "g"),
  // ApiError(403, "PASSWORD_CHANGE_REQUIRED", ...)
  new RegExp(String.raw`\bApiError\(\s*\d{3},\s*${CODE}`, "g"),
  // error_response(403, "CSRF_FAILED", ...) / respond(request, 404, "NOT_FOUND", ...)
  new RegExp(String.raw`\b(?:error_response|respond)\(\s*(?:request,\s*)?(?:\d{3}|[a-z_.]+),\s*${CODE}`, "g"),
  // _STATUS_CODES = {400: "BAD_REQUEST", ...}
  new RegExp(String.raw`^\s*\d{3}:\s*${CODE},?\s*$`, "gm"),
  // _STATUS_CODES.get(status, "HTTP_ERROR")
  new RegExp(String.raw`_STATUS_CODES\.get\([^,]+,\s*${CODE}\)`, "g"),
];

function backendCodes(): Map<string, string> {
  const found = new Map<string, string>();
  for (const [file, text] of Object.entries(sources)) {
    for (const pattern of PATTERNS) {
      for (const match of text.matchAll(pattern)) {
        const code = match[1];
        if (code && !found.has(code)) found.set(code, file.replace(/^(\.\.\/)+/, ""));
      }
    }
  }
  return found;
}

const hasBackend = Object.keys(sources).length > 0;

describe.skipIf(!hasBackend)("backend error codes", () => {
  const codes = backendCodes();

  it("are found in the backend sources (the scan itself works)", () => {
    // Codes every phase has: if these disappear the patterns above are broken.
    for (const code of ["VALIDATION_ERROR", "NOT_AUTHENTICATED", "PERMISSION_DENIED", "CSRF_FAILED"]) {
      expect(codes.has(code), code).toBe(true);
    }
    for (const code of ["INVALID_CREDENTIALS", "ACCOUNT_LOCKED", "PASSWORD_CHANGE_REQUIRED", "INTERNAL_ERROR"]) {
      expect(codes.has(code), code).toBe(true);
    }
    expect(codes.size).toBeGreaterThanOrEqual(20);
  });

  it.each([
    ["en", en.errors],
    ["ar", ar.errors],
  ] as const)("all have %s text in the errors namespace", (_lang, messages) => {
    const missing = [...codes].filter(([code]) => !(code in messages)).map(([code, file]) => `${code} (${file})`);
    expect(missing, "add these to src/i18n/locales/{ar,en}/errors.json").toEqual([]);
  });
});
