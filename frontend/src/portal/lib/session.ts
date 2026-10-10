import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useCallback } from "react";

import { portalKeys, portalLogout } from "../api";

/** Ends the portal session, forgets every portal answer and returns to sign-in. */
export function useSignOut(): (reason: "expired" | "signed-out") => Promise<void> {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  return useCallback(
    async (reason: "expired" | "signed-out") => {
      try {
        await portalLogout();
      } catch {
        // The session may already be gone; the cookie is cleared either way.
      }
      queryClient.removeQueries({ queryKey: portalKeys.all });
      queryClient.setQueryData(portalKeys.me, null);
      await navigate({ to: "/portal", search: { reason } });
    },
    [queryClient, navigate],
  );
}
