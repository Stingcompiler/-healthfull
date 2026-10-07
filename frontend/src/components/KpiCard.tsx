import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export interface KpiTrend {
  direction: "up" | "down" | "flat";
  /** Already formatted change, e.g. "12%" or a MoneyText. */
  value?: ReactNode;
  /** Whether "up" is good (visits) or bad (pending transfers). Default true. */
  upIsGood?: boolean;
  /** Comparison label; defaults to "vs. yesterday". */
  label?: ReactNode;
}

export interface KpiCardProps {
  label: ReactNode;
  value: ReactNode;
  icon?: ReactNode;
  trend?: KpiTrend;
  /** Secondary line under the value. */
  hint?: ReactNode;
  loading?: boolean;
  /** Accent for the icon tile. */
  tone?: "primary" | "success" | "warning" | "danger" | "info";
  /**
   * Element of the label. Default "h2" (cards directly under the page's h1); use "h3"/"h4"
   * inside a titled section, or "p" when the card is not part of the outline.
   */
  headingLevel?: "h2" | "h3" | "h4" | "p";
  className?: string;
}

const toneClasses: Record<NonNullable<KpiCardProps["tone"]>, string> = {
  primary: "bg-primary-soft text-primary-strong",
  success: "bg-success-bg text-success-fg",
  warning: "bg-warning-bg text-warning-fg",
  danger: "bg-danger-bg text-danger-fg",
  info: "bg-info-bg text-info-fg",
};

export function KpiCard({
  label,
  value,
  icon,
  trend,
  hint,
  loading = false,
  tone = "primary",
  headingLevel: Heading = "h2",
  className,
}: KpiCardProps) {
  const { t } = useTranslation();
  return (
    <section
      data-slot="kpi-card"
      className={cn("card-surface @container flex min-w-0 flex-col gap-3 p-4 md:p-5", className)}
    >
      <div className="flex items-start justify-between gap-2">
        <Heading className="min-w-0 text-sm font-medium text-muted">{label}</Heading>
        {icon ? (
          <div
            className={cn(
              "flex size-9 shrink-0 items-center justify-center rounded-control [&_svg]:size-[18px]",
              toneClasses[tone],
            )}
            aria-hidden="true"
          >
            {icon}
          </div>
        ) : null}
      </div>
      {loading ? (
        <Skeleton className="h-8 w-28" />
      ) : (
        // Container-query sizing keeps long values (money) on one line in narrow
        // grid cells instead of truncating them.
        <div className="tabular text-xl leading-tight font-bold break-words text-fg @[14rem]:text-2xl @[18rem]:text-[1.75rem] [&_[data-slot=money]]:whitespace-normal">
          {value}
        </div>
      )}
      {trend || hint ? (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
          {trend ? <TrendPill trend={trend} /> : null}
          {trend ? <span className="text-muted">{trend.label ?? t("kpi.comparedToYesterday")}</span> : null}
          {hint ? <span className="text-muted">{hint}</span> : null}
        </div>
      ) : null}
    </section>
  );
}

function TrendPill({ trend }: { trend: KpiTrend }) {
  const { t } = useTranslation();
  const { direction, value, upIsGood = true } = trend;
  const good = direction === "flat" ? null : (direction === "up") === upIsGood;
  const Icon = direction === "up" ? TrendingUp : direction === "down" ? TrendingDown : Minus;
  // Only the direction word is screen-reader-only; the value itself stays exposed, so any
  // ReactNode (MoneyText, a formatted number) is read after it: "Up 12%".
  const srText = direction === "up" ? t("kpi.trendUp") : direction === "down" ? t("kpi.trendDown") : t("kpi.trendFlat");
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium",
        good === null && "bg-subtle text-muted",
        good === true && "bg-success-bg text-success-fg",
        good === false && "bg-danger-bg text-danger-fg",
      )}
    >
      <Icon className="size-3.5" aria-hidden="true" />
      <span className="sr-only">{srText} </span>
      {value !== undefined ? <span>{value}</span> : null}
    </span>
  );
}
