import type { ApiErrorBody } from "./contract";

/**
 * Error codes the frontend itself produces when the server did not send a
 * `{code, message, details}` body (network down, proxy HTML page, ...).
 * Server codes (INVALID_CREDENTIALS, STOCK_INSUFFICIENT, ...) pass through
 * unchanged. Every code is translated in the `errors` i18n namespace.
 */
export const CLIENT_ERROR_CODES = {
  network: "NETWORK_ERROR",
  validation: "VALIDATION_ERROR",
  unauthenticated: "NOT_AUTHENTICATED",
  forbidden: "PERMISSION_DENIED",
  notFound: "NOT_FOUND",
  conflict: "CONFLICT",
  locked: "ACCOUNT_LOCKED",
  rateLimited: "RATE_LIMITED",
  server: "SERVER_ERROR",
  unavailable: "SERVICE_UNAVAILABLE",
  csrf: "CSRF_FAILED",
  unknown: "UNKNOWN_ERROR",
} as const;

export class ApiError extends Error implements ApiErrorBody {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message || body.code);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details;
  }

  toJSON(): ApiErrorBody & { status: number } {
    return { status: this.status, code: this.code, message: this.message, details: this.details };
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function codeForStatus(status: number): string {
  if (status === 0) return CLIENT_ERROR_CODES.network;
  if (status === 400 || status === 422) return CLIENT_ERROR_CODES.validation;
  if (status === 401) return CLIENT_ERROR_CODES.unauthenticated;
  if (status === 403) return CLIENT_ERROR_CODES.forbidden;
  if (status === 404) return CLIENT_ERROR_CODES.notFound;
  if (status === 409) return CLIENT_ERROR_CODES.conflict;
  if (status === 423) return CLIENT_ERROR_CODES.locked;
  if (status === 429) return CLIENT_ERROR_CODES.rateLimited;
  if (status === 502 || status === 503 || status === 504) return CLIENT_ERROR_CODES.unavailable;
  if (status >= 500) return CLIENT_ERROR_CODES.server;
  return CLIENT_ERROR_CODES.unknown;
}

const CODE_RE = /^[A-Z][A-Z0-9_]*$/;

/**
 * Turns whatever the server (or the network) returned into the uniform
 * `{code, message, details}` shape.
 *
 * Handles, in order:
 *  - the contract body `{code, message, details}`
 *  - django-ninja's default `{detail: [...]}` validation body (422)
 *  - `{detail: "..."}` bodies, e.g. Django's CSRF failure (403)
 *  - anything else (HTML error pages, empty bodies) by HTTP status
 */
export function normalizeError(status: number, body: unknown): ApiError {
  if (isRecord(body) && typeof body.code === "string" && CODE_RE.test(body.code)) {
    return new ApiError(status, {
      code: body.code,
      message: typeof body.message === "string" ? body.message : "",
      details: isRecord(body.details) ? body.details : {},
    });
  }

  if (isRecord(body) && Array.isArray(body.detail)) {
    return new ApiError(status, {
      code: CLIENT_ERROR_CODES.validation,
      message: "",
      details: { errors: body.detail },
    });
  }

  if (isRecord(body) && typeof body.detail === "string") {
    const isCsrf = status === 403 && /csrf/i.test(body.detail);
    return new ApiError(status, {
      code: isCsrf ? CLIENT_ERROR_CODES.csrf : codeForStatus(status),
      message: body.detail,
      details: {},
    });
  }

  return new ApiError(status, { code: codeForStatus(status), message: "", details: {} });
}

/** Wraps a thrown fetch/transport failure (offline, DNS, aborted). */
export function networkError(cause: unknown): ApiError {
  const message = cause instanceof Error ? cause.message : String(cause);
  return new ApiError(0, { code: CLIENT_ERROR_CODES.network, message, details: {} });
}

/** Any thrown value as an ApiError, for UI code that only shows a message. */
export function toApiError(error: unknown): ApiError {
  if (isApiError(error)) return error;
  if (error instanceof TypeError) return networkError(error);
  return new ApiError(0, {
    code: CLIENT_ERROR_CODES.unknown,
    message: error instanceof Error ? error.message : "",
    details: {},
  });
}
