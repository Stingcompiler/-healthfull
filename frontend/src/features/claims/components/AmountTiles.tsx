import type { ReactNode } from "react";

import { MoneyText } from "@/components/MoneyText";
import { cn } from "@/lib/utils";

export interface AmountTile {
  key: string;
  label: ReactNode;
  value: string;
  /** Accent bar on the inline start edge. */
  tone?: "primary" | "info" | "success" | "warning" | "danger";
  strong?: boolean;
}

const TONE: Record<NonNullable<AmountTile["tone"]>, string> = {
  primary: "border-s-primary",
  info: "border-s-info",
  success: "border-s-success",
  warning: "border-s-warning",
  danger: "border-s-danger",
};

/**
 * A row of money totals that stays readable on phones: two per row at 375 px with amounts on
 * one line (KPI cards wrap a long amount there), more per row as the screen widens.
 */
export function AmountTiles({
  tiles,
  className,
  testId,
}: {
  tiles: readonly AmountTile[];
  className?: string;
  testId?: string;
}) {
  return (
    <dl className={cn("grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5", className)} data-testid={testId}>
      {tiles.map((tile) => (
        <div
          key={tile.key}
          className={cn(
            "card-surface flex min-w-0 flex-col gap-1 border-s-4 px-3 py-2.5",
            tile.tone ? TONE[tile.tone] : "border-s-border",
          )}
        >
          <dt className="text-xs text-muted">{tile.label}</dt>
          <dd>
            <MoneyText value={tile.value} className={cn("text-base", tile.strong && "font-bold")} />
          </dd>
        </div>
      ))}
    </dl>
  );
}
