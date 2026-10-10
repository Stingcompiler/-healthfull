/**
 * The signed-in user's in-app notifications (FEATURES 0.13): the bell's unread count (polled
 * on the LAN, no push channel) and the latest notifications, read and marked through
 * /api/core/notifications.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type AppNotification = components["schemas"]["NotificationOut"];

export const notificationKeys = {
  all: ["notifications"] as const,
  count: ["notifications", "count"] as const,
  latest: ["notifications", "latest"] as const,
};

/** How often the bell asks for the unread count. */
export const POLL_MS = 60_000;
/** Notifications the popover lists. */
export const LATEST = 15;

export function useUnreadCount() {
  return useQuery({
    queryKey: notificationKeys.count,
    queryFn: () => unwrap(api.GET("/api/core/notifications/unread-count")),
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
  });
}

export function useLatestNotifications(enabled: boolean) {
  return useQuery({
    queryKey: notificationKeys.latest,
    queryFn: () => unwrap(api.GET("/api/core/notifications", { params: { query: { page_size: LATEST } } })),
    enabled,
  });
}

export function useMarkRead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(api.POST("/api/core/notifications/{notification_id}/read", { params: { path: { notification_id: id } } })),
    onSettled: () => client.invalidateQueries({ queryKey: notificationKeys.all }),
  });
}

export function useMarkAllRead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/core/notifications/read-all")),
    onSettled: () => client.invalidateQueries({ queryKey: notificationKeys.all }),
  });
}
