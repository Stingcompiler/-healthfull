import type { ReactNode } from "react";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

const ALL = "__all__";

export interface FilterOption {
  value: string;
  label: ReactNode;
}

/** A compact select for list filters, with an "all" choice that maps to undefined. */
export function FilterSelect({
  label,
  allLabel,
  value,
  onChange,
  options,
  className,
}: {
  label: string;
  allLabel: ReactNode;
  value: string | undefined;
  onChange: (value: string | undefined) => void;
  options: readonly FilterOption[];
  className?: string;
}) {
  return (
    <Select
      value={value ?? ALL}
      onValueChange={(v) => {
        onChange(v === ALL ? undefined : v);
      }}
    >
      <SelectTrigger aria-label={label} className={cn("w-full sm:w-48", className)}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{allLabel}</SelectItem>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** The row of filters above a list: stacked on phones, inline from sm. */
export function FilterBar({ children }: { children: ReactNode }) {
  return <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">{children}</div>;
}
