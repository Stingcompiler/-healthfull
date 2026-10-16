import { CircleAlert, CircleCheck, Info, TriangleAlert, type LucideIcon } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

export type DecisionTone = "neutral" | "info" | "success" | "warning" | "danger";

const toneIcon: Record<DecisionTone, LucideIcon> = {
  neutral: Info,
  info: Info,
  success: CircleCheck,
  warning: TriangleAlert,
  danger: CircleAlert,
};

/** Colour only for what needs a decision: warning and danger. The rest reads as plain text. */
const toneClasses: Record<DecisionTone, { icon: string; count: string }> = {
  neutral: { icon: "text-muted", count: "text-fg" },
  info: { icon: "text-muted", count: "text-fg" },
  success: { icon: "text-muted", count: "text-fg" },
  warning: { icon: "text-warning", count: "text-warning-fg" },
  danger: { icon: "text-danger", count: "text-danger-fg" },
};

/**
 * Alerts and open decisions as divided rows inside ONE bordered surface (not a card each).
 * AlertCard stays for global bars and page-level messages.
 */
export function DecisionList({ className, ...props }: ComponentProps<"ul">) {
  return (
    <ul
      data-slot="decision-list"
      className={cn("divide-y divide-border overflow-hidden rounded-card border border-border bg-surface", className)}
      {...props}
    />
  );
}

export interface DecisionRowProps {
  tone?: DecisionTone;
  /** The number the row is about (affected items). */
  count?: ReactNode;
  /** What it is. */
  title: ReactNode;
  /** A secondary figure, e.g. a MoneyText. */
  detail?: ReactNode;
  /** The way to resolve it: a link or button. */
  action?: ReactNode;
  className?: string;
}

export function DecisionRow({ tone = "neutral", count, title, detail, action, className }: DecisionRowProps) {
  const Icon = toneIcon[tone];
  const classes = toneClasses[tone];
  return (
    <li
      data-slot="decision-row"
      data-tone={tone}
      className={cn("flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3", className)}
    >
      <Icon className={cn("size-4 shrink-0", classes.icon)} aria-hidden="true" />
      <div className="min-w-0 flex-1 basis-40 text-sm leading-6 text-fg">
        {count !== undefined ? (
          <span className={cn("me-1.5 tabular text-base font-bold", classes.count)}>{count}</span>
        ) : null}
        <span>{title}</span>
        {detail ? <span className="ms-2 text-muted">{detail}</span> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </li>
  );
}
