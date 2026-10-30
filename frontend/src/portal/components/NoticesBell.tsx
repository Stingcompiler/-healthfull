import { Link } from "@tanstack/react-router";
import { Bell } from "lucide-react";
import { useTranslation } from "react-i18next";

import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";

import { useNotices } from "../api";

/**
 * The portal header's inbox link (public site Phase 5): a bell with the unread count as a badge.
 * Only rendered for a signed-in patient; the count refreshes every minute.
 */
export function NoticesBell() {
  const { t } = useTranslation("portal");
  const language = useLanguage();
  const notices = useNotices();
  const unread = notices.data?.unread ?? 0;
  const badge = unread > 99 ? t("notices.many") : formatNumber(unread, language);
  return (
    <Link
      to="/portal/notices"
      className="relative inline-flex size-11 items-center justify-center rounded-control text-fg focus-ring hover:bg-accent"
      aria-label={unread > 0 ? t("notices.bellUnread", { count: unread }) : t("notices.bell")}
      title={t("notices.bell")}
      data-testid="portal-notices-bell"
    >
      <Bell className="size-5" aria-hidden="true" />
      {unread > 0 ? (
        <span
          className="absolute end-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] leading-none font-semibold text-danger-contrast tabular-nums"
          aria-hidden="true"
          data-testid="portal-notices-badge"
        >
          {badge}
        </span>
      ) : null}
    </Link>
  );
}
