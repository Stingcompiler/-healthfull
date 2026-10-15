import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
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
  /** Kept for compatibility; no longer rendered (direction A: no icon tiles). */
  icon?: ReactNode;
  trend?: KpiTrend;
  /** Secondary line under the value. */
  hint?: ReactNode;
  loading?: boolean;
  /**
   * Colour is spent only on figures that need a decision: "warning" and "danger" tint the
   * value; every other tone renders as a plain figure.
   */
  tone?: "primary" | "success" | "warning" | "danger" | "info";
  /** The one figure a screen is about: larger than its siblings. */
  hero?: boolean;
  /** No surface of its own: the card sits inside a KpiGroup. */
  bare?: boolean;
  /**
   * Element of the label. Default "h2" (cards directly under the page's h1); use "h3"/"h4"
   * inside a titled section, or "p" when the card is not part of the outline.
   */
  headingLevel?: "h2" | "h3" | "h4" | "p";
  className?: string;
}

/**
 * Container-query sizing: the figure scales with the width of its own cell and never wraps
 * (an amount split over two lines is unreadable), so a long value shrinks instead.
 */
const valueSize = {
  normal: "text-lg @[10rem]:text-xl @[13rem]:text-2xl",
  hero: "text-2xl @[14rem]:text-3xl @[22rem]:text-4xl",
};

export function KpiCard({
  label,
  value,
  trend,
  hint,
  loading = false,
  tone = "primary",
  hero = false,
  bare = false,
  headingLevel: Heading = "h2",
  className,
}: KpiCardProps) {
  const { t } = useTranslation();
  return (
    <section
      data-slot="kpi-card"
      data-hero={hero || undefined}
      className={cn(
        "@container flex min-w-0 flex-col gap-1.5 p-4 md:p-5",
        bare ? "bg-surface" : "card-surface",
        className,
      )}
    >
      <Heading className="min-w-0 text-sm font-medium text-muted">{label}</Heading>
      {loading ? (
        <Skeleton className={hero ? "h-10 w-40" : "h-7 w-28"} />
      ) : (
        <div
          className={cn(
            "tabular leading-tight whitespace-nowrap text-fg",
            hero ? cn("font-bold", valueSize.hero) : cn("font-semibold", valueSize.normal),
            tone === "danger" && "text-danger-fg",
            tone === "warning" && "text-warning-fg",
            "[&_[data-slot=money]]:font-[inherit]",
          )}
        >
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

/**
 * One bordered surface holding a hero figure and the figures a step below it, separated by
 * hairlines (not a row of equal cards). Children are `<KpiCard bare>`.
 */
export function KpiGroup({ children, className, ...props }: ComponentProps<"section">) {
  return (
    <section
      data-slot="kpi-group"
      className={cn("grid grid-cols-2 gap-px overflow-hidden rounded-card border border-border bg-border", className)}
      {...props}
    >
      {children}
    </section>
  );
}

function TrendPill({ trend }: { trend: KpiTrend }) {
  const { t } = useTranslation();
  const { direction, value, upIsGood = true } = trend;
  const bad = direction === "flat" ? false : (direction === "up") !== upIsGood;
  const Icon = direction === "up" ? TrendingUp : direction === "down" ? TrendingDown : Minus;
  // Only the direction word is screen-reader-only; the value itself stays exposed, so any
  // ReactNode (MoneyText, a formatted number) is read after it: "Up 12%".
  const srText = direction === "up" ? t("kpi.trendUp") : direction === "down" ? t("kpi.trendDown") : t("kpi.trendFlat");
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full font-medium",
        // Tint only when the movement is a bad one (it needs a look); good or flat stays plain.
        bad ? "bg-danger-bg px-2 py-0.5 text-danger-fg" : "text-muted",
      )}
    >
      <Icon className="size-3.5" aria-hidden="true" />
      <span className="sr-only">{srText} </span>
      {value !== undefined ? <span>{value}</span> : null}
    </span>
  );
}
