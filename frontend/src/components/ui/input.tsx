import * as React from "react";

import { cn } from "@/lib/utils";

export const controlClasses = [
  "w-full min-w-0 rounded-control border border-border-strong/70 bg-surface text-fg shadow-xs",
  "transition-[border-color,box-shadow] duration-150 outline-none",
  "placeholder:text-muted",
  "hover:border-border-strong",
  "focus-visible:border-primary focus-visible:ring-3 focus-visible:ring-ring/25",
  "disabled:cursor-not-allowed disabled:bg-subtle disabled:opacity-70",
  "aria-invalid:border-danger aria-invalid:ring-danger/20 aria-invalid:focus-visible:ring-danger/25",
].join(" ");

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        controlClasses,
        "h-10 px-3 py-2 text-sm",
        "file:me-3 file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-fg",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
