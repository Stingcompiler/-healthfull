/**
 * Contract guard: every error code the backend can put in an API response has
 * Arabic and English text in the `errors` namespace (ARCHITECTURE 4.11: "the
 * frontend maps `code` to translated text"). Without it the UI falls back to
 * the server's English `message`, also for Arabic users.
 *
 * The codes are read from the backend sources: DomainError(...) in domain/,
 * services and models (409 unless mapped otherwise), codes passed to private
 * helpers that raise it, and the HTTP layer in api/ (status map, ApiError,
 * error responses). Adding a code there without translating it fails
 * `pnpm test` (and `make check`). A text may interpolate `{{key}}` only when
 * every raise of its code passes that `details` key.
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

/** Codes handed to a private helper that builds the DomainError (its details are not visible here). */
const HELPER_PATTERNS: readonly RegExp[] = [
  // raise _error("LINE_NOT_PAYABLE", message, status) in domain/service_line.py
  new RegExp(String.raw`\braise\s+_\w+\(\s*${CODE}`, "g"),
  // _choice(severity, Severity, "INVALID_SEVERITY") in apps/clinical/services.py
  new RegExp(String.raw`\b_choice\([^()]*,\s*${CODE}\s*\)`, "g"),
  // _require_open(status, cancelled_code="LINE_ALREADY_CANCELLED")
  new RegExp(String.raw`\bcancelled_code=${CODE}`, "g"),
];

const shortPath = (file: string): string => file.replace(/^(\.\.\/)+/, "");

function scan(patterns: readonly RegExp[]): Map<string, string> {
  const found = new Map<string, string>();
  for (const [file, text] of Object.entries(sources)) {
    for (const pattern of patterns) {
      for (const match of text.matchAll(pattern)) {
        const code = match[1];
        if (code && !found.has(code)) found.set(code, shortPath(file));
      }
    }
  }
  return found;
}

function backendCodes(): Map<string, string> {
  return new Map([...scan(HELPER_PATTERNS), ...scan(PATTERNS)]);
}

/** Keyword argument names of the Python call whose "(" is at `open` (strings and nested brackets skipped). */
function keywordArguments(text: string, open: number): Set<string> {
  let depth = 0;
  let quote = "";
  let topLevel = "";
  for (let i = open; i < text.length; i++) {
    const ch = text.charAt(i);
    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = "";
    } else if (ch === '"' || ch === "'") quote = ch;
    else if ("([{".includes(ch)) depth++;
    else if (")]}".includes(ch)) {
      depth--;
      if (depth === 0) break;
    } else if (depth === 1) topLevel += ch;
  }
  return new Set([...topLevel.matchAll(/(?:^|,)\s*(\w+)\s*=(?!=)/g)].map((m) => m[1] ?? ""));
}

/** For each code, the detail keys of every literal `DomainError("CODE", ...)` / `ApiError(409, "CODE", ...)`. */
function raiseSites(): Map<string, { file: string; keys: Set<string> }[]> {
  const raise = new RegExp(String.raw`\b(?:DomainError|ApiError)\(\s*(?:\d{3},\s*)?${CODE}`, "g");
  const sites = new Map<string, { file: string; keys: Set<string> }[]>();
  for (const [file, text] of Object.entries(sources)) {
    for (const match of text.matchAll(raise)) {
      const code = match[1] ?? "";
      const keys = keywordArguments(text, match.index + match[0].indexOf("("));
      sites.set(code, [...(sites.get(code) ?? []), { file: shortPath(file), keys }]);
    }
  }
  return sites;
}

function placeholders(text: string): string[] {
  return [...text.matchAll(/\{\{\s*(\w+)\s*(?:,[^}]*)?\}\}/g)].map((m) => m[1] ?? "");
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

  it("finds codes raised through private helpers", () => {
    for (const code of ["LINE_NOT_PAYABLE", "LINE_ALREADY_CANCELLED", "INVALID_SEVERITY"]) {
      expect(codes.has(code), code).toBe(true);
    }
  });

  // An unfilled placeholder is shown literally ("{{available}}"), so a text may only use a
  // details key that every raise of its code sends.
  it.each([
    ["en", en.errors],
    ["ar", ar.errors],
  ] as const)("%s placeholders are details every raise of the code sends", (_lang, messages) => {
    const sites = raiseSites();
    const viaHelper = scan(HELPER_PATTERNS);
    const problems: string[] = [];
    for (const [code, text] of Object.entries(messages)) {
      for (const name of placeholders(text)) {
        const calls = sites.get(code) ?? [];
        if (calls.length === 0 || viaHelper.has(code)) problems.push(`${code}: {{${name}}} has no checkable raise`);
        for (const call of calls) {
          if (!call.keys.has(name)) problems.push(`${code}: {{${name}}} is not sent by ${call.file}`);
        }
      }
    }
    expect(problems, "drop the placeholder or pass the key at every raise").toEqual([]);
  });
});
