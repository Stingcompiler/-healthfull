import { RadioGroup as RadioGroupPrimitive } from "radix-ui";
import * as React from "react";

import { cn } from "@/lib/utils";

function RadioGroup({ className, ...props }: React.ComponentProps<typeof RadioGroupPrimitive.Root>) {
  return <RadioGroupPrimitive.Root data-slot="radio-group" className={cn("grid gap-3", className)} {...props} />;
}

function RadioGroupItem({ className, ...props }: React.ComponentProps<typeof RadioGroupPrimitive.Item>) {
  return (
    <RadioGroupPrimitive.Item
      data-slot="radio-group-item"
      className={cn(
        "aspect-square size-[18px] shrink-0 rounded-full border border-border-strong bg-surface text-primary shadow-xs transition-[border-color,box-shadow]",
        "focus-ring",
        "disabled:cursor-not-allowed disabled:opacity-55",
        "data-[state=checked]:border-primary",
        "aria-invalid:border-danger",
        className,
      )}
      {...props}
    >
      <RadioGroupPrimitive.Indicator
        data-slot="radio-group-indicator"
        className="relative flex items-center justify-center"
      >
        <span className="size-2.5 rounded-full bg-primary" />
      </RadioGroupPrimitive.Indicator>
    </RadioGroupPrimitive.Item>
  );
}

/**
 * A radio drawn as one segment of a segmented control (a choice that shows no panel, e.g. a
 * payment method). Put several in a `RadioGroup` with `className="flex flex-wrap gap-1
 * rounded-control bg-subtle p-1"`; the checked one is raised and outlined.
 */
function RadioGroupSegment({ className, ...props }: React.ComponentProps<typeof RadioGroupPrimitive.Item>) {
  return (
    <RadioGroupPrimitive.Item
      data-slot="radio-group-segment"
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-[6px] px-3 text-sm font-medium whitespace-nowrap text-muted",
        "transition-[color,background-color,box-shadow] hover:text-fg",
        "focus-ring-inset",
        "disabled:pointer-events-none disabled:opacity-50",
        "data-[state=checked]:bg-surface data-[state=checked]:text-fg data-[state=checked]:shadow-card",
        "data-[state=checked]:ring-1 data-[state=checked]:ring-primary",
        "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      {...props}
    />
  );
}

export { RadioGroup, RadioGroupItem, RadioGroupSegment };
