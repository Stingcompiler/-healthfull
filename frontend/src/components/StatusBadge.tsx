import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

import { STATUS_STYLES, type Status } from "./status";

export type { ServiceLineState, Status, VerificationState } from "./status";

export interface StatusBadgeProps {
  status: Status;
  /** "md" default; "sm" for dense tables. */
  size?: "sm" | "md";
  /** Show the explanatory hint as a native tooltip. Default true. */
  withHint?: boolean;
  className?: string;
}

export function StatusBadge({ status, size = "md", withHint = true, className }: StatusBadgeProps) {
  const { t } = useTranslation();
  const style = STATUS_STYLES[status];
  const Icon = style.icon;
  return (
    <span
      data-slot="status-badge"
      data-status={status}
      title={withHint ? t(`statusHint.${status}`) : undefined}
      className={cn(
        "inline-flex w-fit shrink-0 items-center gap-1 rounded-full font-medium whitespace-nowrap",
        size === "sm" ? "px-2 py-0.5 text-[11px] leading-4" : "px-2.5 py-1 text-xs leading-4",
        style.className,
        className,
      )}
    >
      <Icon aria-hidden="true" className={size === "sm" ? "size-3" : "size-3.5"} />
      {t(`status.${status}`)}
    </span>
  );
}
