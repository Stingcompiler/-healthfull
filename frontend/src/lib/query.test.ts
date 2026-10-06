import { MutationObserver } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/errors";
import type { MeOut } from "@/lib/api/contract";
import { authKeys } from "@/lib/auth/api";

import { createQueryClient, PASSWORD_CHANGE_REQUIRED } from "./query";

const ME: MeOut = {
  id: 1,
  username: "cashier",
  full_name_ar: "محمد عثمان",
  full_name_en: "Mohamed Osman",
  roles: ["cashier"],
  permissions: [],
  language: "ar",
  theme: "light",
  must_change_password: false,
};

function failWith(status: number, code: string) {
  return () => Promise.reject(new ApiError(status, { code, message: code, details: {} }));
}

async function failingQuery(status: number, code: string) {
  const client = createQueryClient();
  client.setQueryData(authKeys.me, ME);
  await expect(
    client.query({ queryKey: ["probe"], queryFn: failWith(status, code), retry: false }),
  ).rejects.toBeInstanceOf(ApiError);
  return client;
}

describe("query client error handling", () => {
  it("forgets the current user when any query answers 401", async () => {
    const client = await failingQuery(401, "NOT_AUTHENTICATED");
    expect(client.getQueryData(authKeys.me)).toBeNull();
  });

  it("forgets the current user when a mutation answers 401", async () => {
    const client = createQueryClient();
    client.setQueryData(authKeys.me, ME);
    const observer = new MutationObserver(client, { mutationFn: failWith(401, "NOT_AUTHENTICATED") });
    await expect(observer.mutate()).rejects.toBeInstanceOf(ApiError);
    expect(client.getQueryData(authKeys.me)).toBeNull();
  });

  it("re-reads /me when the server requires a password change", async () => {
    const client = await failingQuery(403, PASSWORD_CHANGE_REQUIRED);
    // Still signed in, but /me must be fetched again (it now reports must_change_password).
    expect(client.getQueryData(authKeys.me)).toEqual(ME);
    expect(client.getQueryState(authKeys.me)?.isInvalidated).toBe(true);
  });

  it("leaves the user alone on other errors", async () => {
    for (const [status, code] of [
      [403, "PERMISSION_DENIED"],
      [409, "SHIFT_NOT_OPEN"],
      [500, "INTERNAL_ERROR"],
    ] as const) {
      const client = await failingQuery(status, code);
      expect(client.getQueryData(authKeys.me), code).toEqual(ME);
      expect(client.getQueryState(authKeys.me)?.isInvalidated, code).toBe(false);
    }
  });
});
