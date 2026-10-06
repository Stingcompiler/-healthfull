import { CircleAlert, CircleCheck, Info, TriangleAlert, X, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

export type AlertVariant = "info" | "success" | "warning" | "danger";

const variants: Record<AlertVariant, { icon: LucideIcon; classes: string; iconClass: string }> = {
  info: { icon: Info, classes: "border-info-border bg-info-bg text-info-fg", iconClass: "text-info" },
  success: {
    icon: CircleCheck,
    classes: "border-success-border bg-success-bg text-success-fg",
    iconClass: "text-success",
  },
  warning: {
    icon: TriangleAlert,
    classes: "border-warning-border bg-warning-bg text-warning-fg",
    iconClass: "text-warning",
  },
  danger: { icon: CircleAlert, classes: "border-danger-border bg-danger-bg text-danger-fg", iconClass: "text-danger" },
};

export interface AlertCardProps {
  variant?: AlertVariant;
  title: ReactNode;
  children?: ReactNode;
  /** Action buttons/links shown under the text. */
  action?: ReactNode;
  icon?: ReactNode;
  /** Announce to screen readers when it appears (errors, results). */
  live?: boolean;
  onDismiss?: () => void;
  className?: string;
}

export function AlertCard({
  variant = "info",
  title,
  children,
  action,
  icon,
  live = false,
  onDismiss,
  className,
}: AlertCardProps) {
  const { t } = useTranslation();
  const v = variants[variant];
  const Icon = v.icon;
  return (
    <div
      data-slot="alert-card"
      data-variant={variant}
      role={live ? (variant === "danger" || variant === "warning" ? "alert" : "status") : undefined}
      className={cn("relative flex gap-3 rounded-card border p-4", v.classes, className)}
    >
      <div className={cn("mt-0.5 shrink-0 [&_svg]:size-5", v.iconClass)} aria-hidden="true">
        {icon ?? <Icon />}
      </div>
      <div className={cn("min-w-0 flex-1", onDismiss && "pe-6")}>
        <div className="text-sm leading-6 font-semibold">{title}</div>
        {children ? <div className="mt-0.5 text-sm leading-6 opacity-95">{children}</div> : null}
        {action ? <div className="mt-3 flex flex-wrap gap-2">{action}</div> : null}
      </div>
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          className="absolute end-2 top-2 inline-flex size-8 items-center justify-center rounded-control transition-colors hover:bg-surface/60 focus-visible:ring-3 focus-visible:ring-ring/35 focus-visible:outline-none"
        >
          <X className="size-4" aria-hidden="true" />
          <span className="sr-only">{t("a11y.dismissAlert")}</span>
        </button>
      ) : null}
    </div>
  );
}
