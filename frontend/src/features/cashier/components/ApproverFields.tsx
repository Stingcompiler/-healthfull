import type { Control, FieldPath, FieldValues } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { PasswordField, SwitchField, TextField } from "@/components/form";

/**
 * A supervisor approves at the cashier's desk by typing their own credentials (ADR 0009).
 * The fields show only when "a supervisor approves" is switched on.
 */
export function ApproverFields<T extends FieldValues>({
  control,
  enabledName,
  usernameName,
  passwordName,
  enabled,
  description,
}: {
  control: Control<T>;
  enabledName: FieldPath<T>;
  usernameName: FieldPath<T>;
  passwordName: FieldPath<T>;
  enabled: boolean;
  description?: string;
}) {
  const { t } = useTranslation("cashier");
  return (
    <fieldset className="grid gap-3 rounded-control border border-border p-3">
      <SwitchField
        control={control}
        name={enabledName}
        label={t("approver.toggle")}
        description={description ?? t("approver.description")}
      />
      {enabled ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField
            control={control}
            name={usernameName}
            label={t("approver.username")}
            autoComplete="off"
            dir="ltr"
            required
          />
          <PasswordField
            control={control}
            name={passwordName}
            label={t("approver.password")}
            autoComplete="new-password"
            required
          />
        </div>
      ) : null}
    </fieldset>
  );
}
