/** The manager dashboard's data (FEATURES 12.10): one request, refreshed every minute. */
import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";

export const dashboardKeys = {
  manager: ["reports", "dashboard"] as const,
};

export function useManagerDashboard(enabled: boolean) {
  return useQuery({
    queryKey: dashboardKeys.manager,
    queryFn: () => unwrap(api.GET("/api/reports/dashboard")),
    enabled,
    refetchInterval: 60_000,
  });
}
