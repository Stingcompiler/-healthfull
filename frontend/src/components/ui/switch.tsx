import { Switch as SwitchPrimitive } from "radix-ui";
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * The thumb moves with logical translation: Radix sets data-state and the
 * thumb uses `ms-*` margins, so it travels toward the inline end in both
 * LTR and RTL without transforms that would need flipping.
 */
function Switch({ className, ...props }: React.ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        "peer inline-flex h-6 w-11 shrink-0 items-center rounded-full border border-transparent p-0.5 shadow-xs transition-colors",
        "focus-ring disabled:cursor-not-allowed disabled:opacity-55",
        // Off track at full --border-strong: >= 3:1 against the surface and the white thumb.
        "data-[state=checked]:bg-primary data-[state=unchecked]:bg-border-strong",
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className={cn(
          "pointer-events-none block size-5 rounded-full bg-surface shadow-card ring-0 transition-[margin]",
          "data-[state=checked]:ms-5 data-[state=unchecked]:ms-0",
        )}
      />
    </SwitchPrimitive.Root>
  );
}

export { Switch };
