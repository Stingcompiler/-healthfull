import type { ReactNode } from "react";

import { MoneyText } from "@/components/MoneyText";
import { cn } from "@/lib/utils";

export interface AmountTile {
  key: string;
  label: ReactNode;
  value: string;
  /** Only warning and danger colour the figure (a decision); every other tone is a plain figure. */
  tone?: "primary" | "info" | "success" | "warning" | "danger";
  strong?: boolean;
}

/**
 * A row of money totals as ONE hairline-divided surface (not a card per number). Cells wrap:
 * two per row at 375 px with amounts on one line, more as the screen widens.
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
    <dl
      className={cn("flex flex-wrap gap-px overflow-hidden rounded-card border border-border bg-border", className)}
      data-testid={testId}
    >
      {tiles.map((tile) => (
        <div key={tile.key} className="flex min-w-36 flex-1 basis-36 flex-col gap-1 bg-surface px-3 py-2.5">
          <dt className="text-xs text-muted">{tile.label}</dt>
          <dd>
            <MoneyText
              value={tile.value}
              className={cn(
                "text-base",
                tile.strong && "font-bold",
                tile.tone === "danger" && "text-danger-fg",
                tile.tone === "warning" && "text-warning-fg",
              )}
            />
          </dd>
        </div>
      ))}
    </dl>
  );
}
