import type { ComponentProps } from "react";

import { comboLabels } from "@/lib/hooks/use-shortcut";
import { cn } from "@/lib/utils";

export function Kbd({ className, ...props }: ComponentProps<"kbd">) {
  return (
    <kbd
      data-slot="kbd"
      dir="ltr"
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center gap-0.5 rounded-[5px] border border-border bg-subtle px-1.5",
        "font-sans text-[11px] leading-none font-medium text-muted shadow-[inset_0_-1px_0_var(--border)]",
        className,
      )}
      {...props}
    />
  );
}

/** Renders a shortcut like "mod+k" as ⌘ K (macOS) or Ctrl K. */
export function KbdCombo({ combo, className }: { combo: string; className?: string }) {
  return (
    <span dir="ltr" className={cn("inline-flex items-center gap-1", className)}>
      {comboLabels(combo).map((key) => (
        <Kbd key={key}>{key}</Kbd>
      ))}
    </span>
  );
}
