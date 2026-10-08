import { Tabs as TabsPrimitive } from "radix-ui";
import * as React from "react";

import { cn } from "@/lib/utils";

function Tabs({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return <TabsPrimitive.Root data-slot="tabs" className={cn("flex flex-col gap-3", className)} {...props} />;
}

function TabsList({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      className={cn(
        // Phones: triggers fill the list, so 52px less the padding gives the 44px touch target
        // of the other controls (Button sizes are h-11 below md); compact from md.
        "inline-flex h-13 w-fit max-w-full scrollbar-thin items-center justify-start gap-1 overflow-x-auto rounded-control bg-subtle p-1 text-muted md:h-10",
        className,
      )}
      {...props}
    />
  );
}

function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        "inline-flex h-full min-h-11 flex-1 items-center justify-center gap-1.5 rounded-[6px] px-3 text-sm font-medium whitespace-nowrap md:min-h-8",
        "transition-[color,background-color,box-shadow] hover:text-fg",
        "focus-ring-inset",
        "disabled:pointer-events-none disabled:opacity-50",
        "data-[state=active]:bg-surface data-[state=active]:text-fg data-[state=active]:shadow-card",
        "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      {...props}
    />
  );
}

function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return <TabsPrimitive.Content data-slot="tabs-content" className={cn("flex-1 focus-ring", className)} {...props} />;
}

export { Tabs, TabsContent, TabsList, TabsTrigger };
