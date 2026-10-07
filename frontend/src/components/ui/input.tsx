import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Shared look of text-entry controls (input, textarea, select trigger).
 *  - Border at full --border-strong strength: >= 3:1 against surfaces (WCAG 1.4.11; the
 *    contrast test checks this token, so it must not be thinned with an alpha here).
 *  - Focus: border and a flush 2px outline in --ring (solid, also visible in forced colors).
 *  - 16px text on phones: iOS Safari zooms the page into any field under 16px on focus.
 */
export const controlClasses = [
  "w-full min-w-0 rounded-control border border-border-strong bg-surface text-fg shadow-xs",
  "transition-[border-color,box-shadow] duration-150",
  "text-base md:text-sm",
  "placeholder:text-muted",
  "focus-visible:border-ring focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-ring",
  "disabled:cursor-not-allowed disabled:bg-subtle disabled:opacity-70",
  "aria-invalid:border-danger aria-invalid:focus-visible:border-danger aria-invalid:focus-visible:outline-danger",
].join(" ");

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        controlClasses,
        "h-11 px-3 py-2 md:h-10",
        "file:me-3 file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-fg",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
