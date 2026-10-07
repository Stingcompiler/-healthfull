import * as React from "react";

import { cn } from "@/lib/utils";

import { controlClasses } from "./input";

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(controlClasses, "field-sizing-content min-h-20 px-3 py-2", className)}
      {...props}
    />
  );
}

export { Textarea };
