import { useNavigate } from "@tanstack/react-router";
import { Bell, BellOff, CheckCheck } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { DateText } from "@/components/DateText";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { cn } from "@/lib/utils";

import { useLatestNotifications, useMarkAllRead, useMarkRead, useUnreadCount, type AppNotification } from "./api";
import { isKnownKind, isUrgent, notificationParams, notificationTarget } from "./kinds";

/**
 * The top-bar bell (FEATURES 0.13): the unread count as a badge and, when opened, the latest
 * notifications. Opening one marks it read and goes to the screen that resolves it.
 */
export function NotificationBell() {
  const { t } = useTranslation("ops");
  const language = useLanguage();
  const [open, setOpen] = useState(false);
  const count = useUnreadCount();
  const latest = useLatestNotifications(open);
  const markRead = useMarkRead();
  const markAll = useMarkAllRead();
  const navigate = useNavigate();
  const unread = count.data?.count ?? 0;
  const badge = unread > 99 ? t("notifications.many") : formatNumber(unread, language);

  const openNote = (note: AppNotification) => {
    if (!note.read_at) markRead.mutate(note.id);
    const target = notificationTarget(note);
    setOpen(false);
    if (!target) return;
    if (target.to === "/clinic/visits/$visitId") {
      void navigate({ to: target.to, params: { visitId: target.visitId } });
    } else if (target.to === "/patients/$patientId") {
      void navigate({ to: target.to, params: { patientId: target.patientId } });
    } else {
      void navigate({ to: target.to });
    }
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          aria-label={unread > 0 ? t("notifications.openUnread", { count: unread }) : t("notifications.open")}
          data-testid="notifications-bell"
        >
          <Bell aria-hidden="true" />
          {unread > 0 ? (
            <span
              className="absolute end-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] leading-none font-semibold text-danger-contrast tabular-nums"
              aria-hidden="true"
              data-testid="notifications-badge"
            >
              {badge}
            </span>
          ) : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[min(22rem,calc(100vw-2rem))] p-0">
        <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold text-fg">{t("notifications.title")}</h2>
          <Button
            variant="ghost"
            size="sm"
            disabled={unread === 0 || markAll.isPending}
            onClick={() => {
              markAll.mutate();
            }}
          >
            <CheckCheck aria-hidden="true" />
            {t("notifications.markAll")}
          </Button>
        </div>
        <div className="max-h-[min(26rem,70dvh)] overflow-y-auto">
          {latest.isPending ? (
            <div className="grid gap-2 p-4" aria-busy="true">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : latest.isError ? (
            <p className="p-4 text-sm text-danger">{t("notifications.failed")}</p>
          ) : latest.data.items.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-4 py-8 text-center text-sm text-muted">
              <BellOff className="size-6" aria-hidden="true" />
              {t("notifications.empty")}
            </div>
          ) : (
            <ul className="divide-y divide-border" data-testid="notifications-list">
              {latest.data.items.map((note) => (
                <li key={note.id}>
                  <button
                    type="button"
                    className={cn(
                      "flex w-full items-start gap-3 px-4 py-3 text-start focus-ring-inset transition-colors hover:bg-accent",
                      !note.read_at && "bg-primary-soft/40",
                    )}
                    data-unread={note.read_at ? undefined : "true"}
                    onClick={() => {
                      openNote(note);
                    }}
                  >
                    <span
                      className={cn(
                        "mt-1.5 size-2 shrink-0 rounded-full",
                        note.read_at ? "bg-transparent" : isUrgent(note.kind) ? "bg-danger" : "bg-primary",
                      )}
                      aria-hidden="true"
                    />
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span
                        className={cn("text-sm break-words", note.read_at ? "text-fg-muted" : "font-medium text-fg")}
                      >
                        {isKnownKind(note.kind)
                          ? t(`notifications.kinds.${note.kind}`, notificationParams(note, language))
                          : t("notifications.kinds.other")}
                      </span>
                      <DateText value={note.created_at} format="relative" className="text-xs text-muted" />
                    </span>
                    {note.read_at ? null : <span className="sr-only">{t("notifications.unread")}</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
