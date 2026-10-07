import { describe, expect, it } from "vitest";

import i18n from "@/i18n";

import { ApiError, CLIENT_ERROR_CODES, networkError, normalizeError, toApiError } from "./errors";
import { translateError } from "./translate-error";

describe("normalizeError", () => {
  it("passes the contract body through", () => {
    const e = normalizeError(423, {
      code: "ACCOUNT_LOCKED",
      message: "Locked",
      details: { locked_until: "2026-10-06T10:00:00Z", retry_after_seconds: 900 },
    });
    expect(e).toBeInstanceOf(ApiError);
    expect(e.toJSON()).toEqual({
      status: 423,
      code: "ACCOUNT_LOCKED",
      message: "Locked",
      details: { locked_until: "2026-10-06T10:00:00Z", retry_after_seconds: 900 },
    });
  });

  it("fills missing message/details", () => {
    const e = normalizeError(409, { code: "STOCK_INSUFFICIENT" });
    expect(e.code).toBe("STOCK_INSUFFICIENT");
    expect(e.message).toBe("STOCK_INSUFFICIENT");
    expect(e.details).toEqual({});
  });

  it("maps django-ninja validation bodies", () => {
    const e = normalizeError(422, { detail: [{ loc: ["body", "username"], msg: "Field required" }] });
    expect(e.code).toBe(CLIENT_ERROR_CODES.validation);
    expect(e.details).toEqual({ errors: [{ loc: ["body", "username"], msg: "Field required" }] });
  });

  it("recognizes Django CSRF failures", () => {
    expect(normalizeError(403, { detail: "CSRF Failed: CSRF token missing." }).code).toBe("CSRF_FAILED");
    expect(normalizeError(403, { detail: "Forbidden" }).code).toBe("PERMISSION_DENIED");
  });

  it.each([
    [401, "NOT_AUTHENTICATED"],
    [403, "PERMISSION_DENIED"],
    [404, "NOT_FOUND"],
    [409, "CONFLICT"],
    [423, "ACCOUNT_LOCKED"],
    [429, "RATE_LIMITED"],
    [500, "SERVER_ERROR"],
    [502, "SERVICE_UNAVAILABLE"],
    [504, "SERVICE_UNAVAILABLE"],
    [418, "UNKNOWN_ERROR"],
  ])("falls back to the HTTP status %i -> %s for non-JSON bodies", (status, code) => {
    expect(normalizeError(status, "<html>proxy error</html>").code).toBe(code);
    expect(normalizeError(status, undefined).code).toBe(code);
  });

  it("ignores bodies whose code is not an error code", () => {
    expect(normalizeError(500, { code: 42 }).code).toBe("SERVER_ERROR");
    expect(normalizeError(500, { code: "not a code" }).code).toBe("SERVER_ERROR");
  });
});

describe("transport errors", () => {
  it("wraps network failures", () => {
    const e = networkError(new TypeError("Failed to fetch"));
    expect(e.status).toBe(0);
    expect(e.code).toBe("NETWORK_ERROR");
  });

  it("toApiError normalizes anything thrown", () => {
    const api = new ApiError(404, { code: "NOT_FOUND", message: "", details: {} });
    expect(toApiError(api)).toBe(api);
    expect(toApiError(new TypeError("x")).code).toBe("NETWORK_ERROR");
    expect(toApiError(new Error("boom")).code).toBe("UNKNOWN_ERROR");
    expect(toApiError("weird").code).toBe("UNKNOWN_ERROR");
  });
});

describe("translateError", () => {
  it("translates known codes in both languages", async () => {
    await i18n.changeLanguage("en");
    expect(translateError("INVALID_CREDENTIALS")).toBe("Incorrect username or password.");
    await i18n.changeLanguage("ar");
    expect(translateError("INVALID_CREDENTIALS")).toBe("اسم المستخدم أو كلمة المرور غير صحيحة.");
  });

  it("falls back to the server message, then to a generic text", async () => {
    await i18n.changeLanguage("en");
    const withMessage = new ApiError(409, { code: "SOME_NEW_RULE", message: "Rule says no", details: {} });
    expect(translateError(withMessage)).toBe("Rule says no");
    expect(translateError("SOME_NEW_RULE")).toBe("An unexpected error occurred. Please try again.");
    await i18n.changeLanguage("ar");
  });
});
