/**
 * Django CSRF handling for the SPA.
 * The token lives in the `csrftoken` cookie (not HttpOnly) and must be echoed
 * in the X-CSRFToken header on unsafe methods. GET /api/auth/csrf sets it.
 */
export const CSRF_COOKIE = "csrftoken";
export const CSRF_HEADER = "X-CSRFToken";
export const CSRF_ENDPOINT = "/api/auth/csrf";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS", "TRACE"]);

export function isUnsafeMethod(method: string): boolean {
  return !SAFE_METHODS.has(method.toUpperCase());
}

export function readCookie(name: string, cookieString = document.cookie): string | null {
  for (const part of cookieString.split(";")) {
    const [rawKey, ...rest] = part.trim().split("=");
    if (rawKey === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

let pending: Promise<string | null> | null = null;

/**
 * Returns the CSRF token, fetching the cookie once if it is missing.
 * Concurrent callers share one request. `force` re-fetches (used after a
 * CSRF failure, e.g. when the cookie was rotated by login).
 */
export async function ensureCsrfToken(
  fetchImpl: typeof fetch = globalThis.fetch,
  force = false,
): Promise<string | null> {
  const existing = readCookie(CSRF_COOKIE);
  if (existing && !force) return existing;
  pending ??= fetchImpl(CSRF_ENDPOINT, { credentials: "include" })
    .then(() => readCookie(CSRF_COOKIE))
    .finally(() => {
      pending = null;
    });
  return pending;
}
