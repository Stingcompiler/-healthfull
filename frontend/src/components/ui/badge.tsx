import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  [
    "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-full border px-2.5 py-0.5",
    "text-xs leading-5 font-medium whitespace-nowrap",
    "[&>svg]:pointer-events-none [&>svg]:size-3.5",
    "focus-ring",
  ],
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-fg",
        soft: "border-transparent bg-primary-soft text-primary-strong",
        neutral: "border-transparent bg-subtle text-fg-muted",
        outline: "border-border text-fg",
        success: "border-success-border bg-success-bg text-success-fg",
        warning: "border-warning-border bg-warning-bg text-warning-fg",
        danger: "border-danger-border bg-danger-bg text-danger-fg",
        info: "border-info-border bg-info-bg text-info-fg",
        // Waiting, and nobody has to act (a claim with the payer, a cheque still clearing). Neutral
        // with a dashed border so it differs from "done" by shape as well as color. Items that need
        // a person to act use `warning`.
        pending: "border-dashed border-state-pending-border bg-state-pending-bg text-state-pending-fg",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

function Badge({
  className,
  variant,
  asChild = false,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span";
  return <Comp data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
