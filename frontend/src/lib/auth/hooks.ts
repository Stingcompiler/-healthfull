import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { MeOut } from "@/lib/api/contract";

import { changePassword, login, logout, meQueryOptions, updatePreferences, authKeys } from "./api";
import { hasPermission } from "./permissions";

export function useMe() {
  return useQuery(meQueryOptions);
}

/** The logged-in user; only call inside authenticated routes. */
export function useCurrentUser(): MeOut | null {
  return useQuery(meQueryOptions).data ?? null;
}

export function usePermission(permission: string | readonly string[] | undefined, mode: "all" | "any" = "all") {
  const me = useCurrentUser();
  return hasPermission(me, permission, mode);
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: login,
    onSuccess: (me) => {
      queryClient.setQueryData(authKeys.me, me);
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: logout,
    onSettled: () => {
      // Drop every cached server response: the next user must not see them.
      queryClient.clear();
      queryClient.setQueryData(authKeys.me, null);
    },
  });
}

export function useChangePassword() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: changePassword,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: authKeys.me });
    },
  });
}

export function useUpdatePreferences() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updatePreferences,
    onSuccess: (me) => {
      queryClient.setQueryData(authKeys.me, me);
    },
  });
}
