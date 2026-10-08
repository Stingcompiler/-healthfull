import type { ReactNode } from "react";
import type { Control, FieldPath, FieldValues } from "react-hook-form";

import { FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/form";
import { Input } from "@/components/ui/input";

/** A native date picker bound to an ISO date string (YYYY-MM-DD) field. */
export function DateField<T extends FieldValues>({
  control,
  name,
  label,
  description,
  required,
  min,
  className,
}: {
  control: Control<T>;
  name: FieldPath<T>;
  label: ReactNode;
  description?: ReactNode;
  required?: boolean;
  min?: string;
  className?: string;
}) {
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem className={className}>
          <FormLabel required={required}>{label}</FormLabel>
          <FormControl>
            <Input type="date" dir="ltr" min={min} {...field} value={field.value ?? ""} />
          </FormControl>
          {description ? <FormDescription>{description}</FormDescription> : null}
          <FormMessage />
        </FormItem>
      )}
    />
  );
}
