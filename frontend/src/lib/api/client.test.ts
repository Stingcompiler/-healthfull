import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, unwrap } from "./client";
import { CSRF_HEADER, readCookie } from "./csrf";
import { ApiError } from "./errors";

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function clearCookies() {
  for (const c of document.cookie.split(";")) {
    const name = c.split("=")[0]?.trim();
    if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  }
}

describe("api client", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    clearCookies();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    clearCookies();
  });

  it("returns data on success", async () => {
    fetchMock.mockResolvedValueOnce(json(200, { status: "ok", db: "ok", version: "1", time: "2026-10-06T00:00:00Z" }));
    const health = await unwrap(api.GET("/api/ops/health"));
    expect(health.status).toBe("ok");
    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.url).toMatch(/\/api\/ops\/health$/);
    expect(request.credentials).toBe("include");
    expect(request.headers.get(CSRF_HEADER)).toBeNull();
  });

  it("fetches the CSRF cookie once before the first unsafe call and sends the header", async () => {
    fetchMock.mockImplementation((input) => {
      const url = typeof input === "string" ? input : input instanceof Request ? input.url : String(input);
      if (url.endsWith("/api/auth/csrf")) {
        document.cookie = "csrftoken=tok123; path=/";
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      return Promise.resolve(new Response(null, { status: 204 }));
    });

    await unwrap(api.POST("/api/auth/logout"));
    await unwrap(api.POST("/api/auth/logout"));

    const urls = fetchMock.mock.calls.map(([input]) =>
      typeof input === "string" ? input : input instanceof Request ? input.url : String(input),
    );
    expect(urls.filter((u) => u.endsWith("/api/auth/csrf"))).toHaveLength(1);
    const posts = fetchMock.mock.calls.map(([input]) => input).filter((i): i is Request => i instanceof Request);
    expect(posts).toHaveLength(2);
    for (const p of posts) expect(p.headers.get(CSRF_HEADER)).toBe("tok123");
    expect(readCookie("csrftoken")).toBe("tok123");
  });

  it("throws normalized ApiErrors", async () => {
    document.cookie = "csrftoken=abc; path=/";
    fetchMock.mockResolvedValueOnce(json(401, { code: "INVALID_CREDENTIALS", message: "Bad", details: {} }));
    const err = await unwrap(api.POST("/api/auth/login", { body: { username: "x", password: "y" } })).catch(
      (e: unknown) => e,
    );
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(401);
    expect((err as ApiError).code).toBe("INVALID_CREDENTIALS");
  });

  it("turns network failures into NETWORK_ERROR", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const err = await unwrap(api.GET("/api/auth/me")).catch((e: unknown) => e);
    expect((err as ApiError).code).toBe("NETWORK_ERROR");
  });

  it("normalizes non-JSON error pages", async () => {
    fetchMock.mockResolvedValueOnce(new Response("<html>Bad gateway</html>", { status: 502 }));
    const err = await unwrap(api.GET("/api/auth/me")).catch((e: unknown) => e);
    expect((err as ApiError).code).toBe("SERVICE_UNAVAILABLE");
  });
});
