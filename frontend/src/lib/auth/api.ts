import { queryOptions } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { ChangePasswordIn, LoginIn, MeOut, PreferencesPatch } from "@/lib/api/contract";
import { ensureCsrfToken } from "@/lib/api/csrf";
import { isApiError } from "@/lib/api/errors";

export const authKeys = {
  me: ["auth", "me"] as const,
};

/** Current user, or null when not logged in (401 is not an error here). */
export async function fetchMe(): Promise<MeOut | null> {
  try {
    return await unwrap(api.GET("/api/auth/me"));
  } catch (error) {
    if (isApiError(error) && error.status === 401) return null;
    throw error;
  }
}

export const meQueryOptions = queryOptions({
  queryKey: authKeys.me,
  queryFn: fetchMe,
  staleTime: 5 * 60_000,
  retry: false,
});

export async function login(body: LoginIn): Promise<MeOut> {
  await ensureCsrfToken();
  return unwrap(api.POST("/api/auth/login", { body }));
}

export async function logout(): Promise<void> {
  await unwrap(api.POST("/api/auth/logout"));
}

export async function changePassword(body: ChangePasswordIn): Promise<void> {
  await unwrap(api.POST("/api/auth/change-password", { body }));
}

export async function updatePreferences(body: PreferencesPatch): Promise<MeOut> {
  return unwrap(api.PATCH("/api/auth/me/preferences", { body }));
}
