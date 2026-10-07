import createClient, { type Middleware } from "openapi-fetch";

import { CSRF_HEADER, ensureCsrfToken, isUnsafeMethod } from "./csrf";
import { networkError, normalizeError } from "./errors";
import type { paths } from "./schema";

/**
 * Same-origin API client. In development Vite proxies /api to Django; in
 * production the reverse proxy serves both from one origin, so the session
 * cookie is first-party.
 */
const csrfMiddleware: Middleware = {
  async onRequest({ request }) {
    if (!isUnsafeMethod(request.method)) return undefined;
    const token = await ensureCsrfToken();
    if (token) request.headers.set(CSRF_HEADER, token);
    return request;
  },
};

export const api = createClient<paths>({
  // Absolute same-origin base: the Fetch spec only resolves relative URLs
  // against a document, and an absolute one also works in workers and tests.
  baseUrl: typeof window === "undefined" ? "" : window.location.origin,
  credentials: "include",
  headers: { Accept: "application/json" },
  // Resolve fetch at call time (not import time) so it can be wrapped/stubbed.
  fetch: (request) => globalThis.fetch(request),
});
api.use(csrfMiddleware);

interface FetchResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/**
 * Awaits an openapi-fetch call and returns its data, or throws a normalized
 * ApiError (`{code, message, details}`), including for network failures.
 *
 *   const me = await unwrap(api.GET("/api/auth/me"));
 */
export async function unwrap<T>(call: Promise<FetchResult<T>>): Promise<T> {
  let result: FetchResult<T>;
  try {
    result = await call;
  } catch (cause) {
    throw networkError(cause);
  }
  const { response } = result;
  if (!response.ok) throw normalizeError(response.status, result.error);
  return result.data as T;
}
