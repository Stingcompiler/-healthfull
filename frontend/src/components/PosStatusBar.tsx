import { CircleCheck, WifiOff } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useMe } from "@/lib/auth/hooks";
import { formatDate } from "@/lib/format";
import { useClock } from "@/lib/hooks/use-clock";
import { useConnection } from "@/lib/hooks/connection-context";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { cn } from "@/lib/utils";

/**
 * The status bar of a point-of-service screen (Design Reference 2.2 section 9: operator, shift,
 * time, and the connection as a quiet indicator). Tablet and desktop only: a phone has no room
 * and no desk. `shift` is the desk's own shift or station text (the cashier's open shift).
 */
export function PosStatusBar({ shift, className }: { shift?: ReactNode; className?: string }) {
  const { t } = useTranslation();
  const language = useLanguage();
  const me = useMe().data;
  const clock = useClock(15_000);
  const connection = useConnection();
  const down = connection === "unreachable";
  const operator = me ? pickName({ ar: me.full_name_ar, en: me.full_name_en }, language) || me.username : "";
  const Icon = down ? WifiOff : CircleCheck;
  return (
    <section
      aria-label={t("statusBar.label")}
      data-testid="pos-status-bar"
      className={cn(
        "sticky bottom-0 z-10 mt-2 hidden flex-wrap items-center gap-x-6 gap-y-1 border-t border-border bg-surface px-3 py-2 text-xs text-muted md:flex",
        className,
      )}
    >
      <p className="flex items-baseline gap-1.5">
        <span>{t("statusBar.operator")}</span>
        <bdi className="font-medium text-fg">{operator}</bdi>
      </p>
      {shift !== undefined ? (
        <p className="flex items-baseline gap-1.5">
          <span>{t("statusBar.shift")}</span>
          <span className="font-medium text-fg">{shift}</span>
        </p>
      ) : null}
      <p className="flex items-baseline gap-1.5">
        <span>{t("statusBar.time")}</span>
        <time dateTime={clock.toISOString()} className="tabular font-medium whitespace-nowrap text-fg">
          {formatDate(clock, language, "time")}
        </time>
      </p>
      <p
        className={cn("ms-auto flex items-center gap-1.5 font-medium", down ? "text-warning-fg" : "text-success-fg")}
        data-testid="pos-connection"
        data-state={connection === "unreachable" ? "unreachable" : "connected"}
      >
        <Icon className="size-3.5" aria-hidden="true" />
        {down ? t("statusBar.unreachable") : t("statusBar.connected")}
      </p>
    </section>
  );
}
