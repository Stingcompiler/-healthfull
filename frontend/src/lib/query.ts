import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { isApiError } from "@/lib/api/errors";
import { authKeys } from "@/lib/auth/api";

/** Statuses where retrying cannot help. */
const NO_RETRY = new Set([400, 401, 403, 404, 409, 422, 423]);

/** 403 code for a user who must change the password first (ADR 0004). */
export const PASSWORD_CHANGE_REQUIRED = "PASSWORD_CHANGE_REQUIRED";

export function createQueryClient(): QueryClient {
  const onError = (error: unknown) => {
    if (!isApiError(error)) return;
    if (error.status === 401) {
      // The session is gone: forget the current user. AuthGuard then sends the
      // user to /login (and back afterwards).
      queryClient.setQueryData(authKeys.me, null);
    } else if (error.status === 403 && error.code === PASSWORD_CHANGE_REQUIRED) {
      // An administrator reset the password while this user was signed in.
      // /api/auth/me still answers and now reports must_change_password, so
      // AuthGuard sends the user to /change-password.
      void queryClient.invalidateQueries({ queryKey: authKeys.me });
    }
  };

  const queryClient: QueryClient = new QueryClient({
    queryCache: new QueryCache({ onError }),
    mutationCache: new MutationCache({ onError }),
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          if (isApiError(error) && NO_RETRY.has(error.status)) return false;
          return failureCount < 2;
        },
      },
      mutations: {
        retry: false,
      },
    },
  });
  return queryClient;
}
