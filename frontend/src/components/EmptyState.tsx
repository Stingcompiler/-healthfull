import { Inbox } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface EmptyStateProps {
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  /** Suggested next step, usually a Button. */
  action?: ReactNode;
  /** Secondary action shown next to the main one. */
  secondaryAction?: ReactNode;
  size?: "default" | "compact";
  /** Render inside a card surface (default) or bare (inside another card). */
  bare?: boolean;
  className?: string;
}

export function EmptyState({
  title,
  description,
  icon,
  action,
  secondaryAction,
  size = "default",
  bare = false,
  className,
}: EmptyStateProps) {
  return (
    <div
      data-slot="empty-state"
      className={cn(
        "flex flex-col items-center justify-center text-center",
        size === "default" ? "gap-4 px-6 py-12 md:py-16" : "gap-3 px-4 py-8",
        !bare && "card-surface",
        className,
      )}
    >
      <div
        aria-hidden="true"
        className={cn(
          "flex items-center justify-center rounded-full bg-primary-soft text-primary-strong ring-8 ring-primary-soft/40",
          size === "default" ? "size-14 [&_svg]:size-7" : "size-11 [&_svg]:size-5",
        )}
      >
        {icon ?? <Inbox />}
      </div>
      <div className="max-w-md">
        <h2 className={cn("font-semibold text-balance text-fg", size === "default" ? "text-lg" : "text-base")}>
          {title}
        </h2>
        {description ? <p className="mt-1.5 text-sm text-pretty text-muted">{description}</p> : null}
      </div>
      {action || secondaryAction ? (
        <div className="flex flex-wrap items-center justify-center gap-2">
          {action}
          {secondaryAction}
        </div>
      ) : null}
    </div>
  );
}
