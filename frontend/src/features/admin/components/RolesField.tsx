import { useId } from "react";
import type { Control, FieldPath, FieldValues } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/form";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { ROLES } from "@/lib/auth/permissions";

/** Role checkboxes bound to a string[] field. */
export function RolesField<T extends FieldValues>({ control, name }: { control: Control<T>; name: FieldPath<T> }) {
  const { t } = useTranslation(["admin", "common"]);
  // A <label> cannot name a div: the group takes its name from the label by id instead.
  const labelId = useId();
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => {
        const selected = new Set<string>(Array.isArray(field.value) ? (field.value as string[]) : []);
        return (
          <FormItem>
            <FormLabel id={labelId} required>
              {t("admin:users.roles")}
            </FormLabel>
            <FormControl>
              <div role="group" aria-labelledby={labelId} className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {ROLES.map((role) => {
                  const id = `role-${name}-${role}`;
                  return (
                    <div key={role} className="flex items-center gap-2.5">
                      <Checkbox
                        id={id}
                        checked={selected.has(role)}
                        onCheckedChange={(checked) => {
                          const next = new Set(selected);
                          if (checked === true) next.add(role);
                          else next.delete(role);
                          field.onChange(ROLES.filter((r) => next.has(r)));
                        }}
                      />
                      <Label htmlFor={id} className="font-normal">
                        {t(`common:roles.${role}`)}
                      </Label>
                    </div>
                  );
                })}
              </div>
            </FormControl>
            <FormMessage />
          </FormItem>
        );
      }}
    />
  );
}
