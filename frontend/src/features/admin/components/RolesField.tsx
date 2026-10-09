import { useId } from "react";
import type { Control, FieldPath, FieldValues } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/form";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { ROLES } from "@/lib/auth/permissions";

/**
 * One option of a checkbox list: the whole row (44px on touch screens, 36px from md) is the
 * label, so a finger never has to hit the 18px box itself.
 */
export function CheckOption({
  id,
  checked,
  onCheckedChange,
  label,
}: {
  id: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: string;
}) {
  return (
    <div className="flex min-h-11 items-center gap-2.5 rounded-control ps-1 hover:bg-accent md:min-h-9">
      <Checkbox
        id={id}
        checked={checked}
        onCheckedChange={(value) => {
          onCheckedChange(value === true);
        }}
      />
      <Label htmlFor={id} className="flex flex-1 cursor-pointer items-center self-stretch font-normal">
        {label}
      </Label>
    </div>
  );
}

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
              <div role="group" aria-labelledby={labelId} className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
                {ROLES.map((role) => (
                  <CheckOption
                    key={role}
                    id={`role-${name}-${role}`}
                    checked={selected.has(role)}
                    onCheckedChange={(checked) => {
                      const next = new Set(selected);
                      if (checked) next.add(role);
                      else next.delete(role);
                      field.onChange(ROLES.filter((r) => next.has(r)));
                    }}
                    label={t(`common:roles.${role}`)}
                  />
                ))}
              </div>
            </FormControl>
            <FormMessage />
          </FormItem>
        );
      }}
    />
  );
}
