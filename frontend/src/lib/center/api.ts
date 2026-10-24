/**
 * The public center page (`GET /api/portal/center-page`): identity, hours, departments,
 * doctors, notices and contact, readable without any sign-in. Used by the portal and by the
 * staff sign-in page. Its key is outside the portal's, so signing out of the portal keeps it.
 */
import { queryOptions, useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type CenterPage = components["schemas"]["PortalCenterPageOut"];
export type CenterHours = components["schemas"]["PortalHoursOut"];
export type CenterToday = components["schemas"]["PortalTodayOut"];
export type CenterDoctor = components["schemas"]["PortalPublicDoctorOut"];
export type CenterClinicDay = components["schemas"]["PortalClinicDayOut"];
export type CenterAnnouncement = components["schemas"]["PortalAnnouncementOut"];

export const centerPageKey = ["center-page"] as const;

export const centerPageQuery = queryOptions({
  queryKey: centerPageKey,
  queryFn: () => unwrap(api.GET("/api/portal/center-page")),
  // Changes rarely: one read per visit is enough, and every read counts against the address.
  staleTime: 5 * 60_000,
  retry: false,
});

export function useCenterPage() {
  return useQuery(centerPageQuery);
}
